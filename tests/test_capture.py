import sys
import time
import types

import numpy as np
import pytest

from uwmirror.capture import CaptureLost, DxcamCapture, FrameUnavailable, output_info_text
from uwmirror.geometry import Region

REGION = Region(1280, 0, 3840, 1440)  # 2560x1440 crop


class FakeDxCamera:
    """Stands in for the object dxcam.create() returns.

    ``get_latest_frame`` paces itself like the real thing (which blocks until
    the next frame) so DxcamCapture's reader thread doesn't spin, and returns
    ``None`` once stopped so the reader exits.
    """

    def __init__(self, width=5120, height=1440):
        self.width = width
        self.height = height
        self.start_kwargs: dict | None = None
        self.stopped = False
        self.released = False
        self.stalled = False
        self.is_capturing = True  # dxcam clears this when its capture loop dies
        self.next_frame: object = np.zeros((1440, 2560, 3), dtype=np.uint8)

    def start(self, **kwargs):
        self.start_kwargs = kwargs

    def get_latest_frame(self):
        while self.stalled and not self.stopped:
            time.sleep(0.005)
        if self.stopped:
            return None
        time.sleep(0.001)  # pace the reader thread
        if isinstance(self.next_frame, Exception):
            raise self.next_frame
        return self.next_frame

    def stop(self):
        self.stopped = True

    def release(self):
        self.released = True


@pytest.fixture
def fake_dxcam(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("dxcam")
    camera = FakeDxCamera()
    module.create_calls = []

    def create(**kwargs):
        module.create_calls.append(kwargs)
        return camera

    module.create = create
    module.output_info = lambda: "Device[0] Output[0]: Res:(5120, 1440) Rot:0 Primary:True\n"
    monkeypatch.setitem(sys.modules, "dxcam", module)
    return module, camera


@pytest.fixture
def started_capture(fake_dxcam):
    """A DxcamCapture that is started and reliably stopped afterwards."""
    _, camera = fake_dxcam
    capture = DxcamCapture(output_idx=0)
    yield capture, camera
    capture.stop()


class TestDxcamCapture:
    def test_create_requests_rgb_numpy_processor_on_the_right_output(self, fake_dxcam):
        """The numpy processor avoids dxcam's default cv2 (opencv) dependency."""
        module, _ = fake_dxcam
        DxcamCapture(output_idx=1, device_idx=2)
        assert module.create_calls == [
            {
                "device_idx": 2,
                "output_idx": 1,
                "output_color": "RGB",
                "processor_backend": "numpy",
            }
        ]

    def test_create_falls_back_when_processor_kwarg_unsupported(self, fake_dxcam, monkeypatch):
        """dxcam-cpp's create() doesn't accept processor_backend."""
        module, camera = fake_dxcam
        calls: list[dict] = []

        def legacy_create(**kwargs):
            calls.append(kwargs)
            if "processor_backend" in kwargs:
                raise TypeError("unexpected keyword argument 'processor_backend'")
            return camera

        monkeypatch.setattr(module, "create", legacy_create)
        capture = DxcamCapture(output_idx=0)
        assert (capture.width, capture.height) == (5120, 1440)
        assert calls[-1] == {"device_idx": 0, "output_idx": 0, "output_color": "RGB"}

    def test_start_passes_video_mode_and_region(self, started_capture):
        """video_mode=True is load-bearing: without it a static desktop stalls."""
        capture, camera = started_capture
        capture.start(REGION, target_fps=60)
        assert camera.start_kwargs == {
            "region": (1280, 0, 3840, 1440),
            "target_fps": 60,
            "video_mode": True,
        }

    def test_dimensions_come_from_camera(self, fake_dxcam):
        capture = DxcamCapture(output_idx=0)
        assert (capture.width, capture.height) == (5120, 1440)

    def test_frame_passthrough(self, started_capture):
        capture, _ = started_capture
        capture.start(REGION, target_fps=60)
        frame = capture.get_latest_frame(timeout=2.0)
        assert frame.shape == (1440, 2560, 3)
        assert frame.dtype == np.uint8

    def test_none_frame_raises_capture_lost(self, started_capture):
        capture, camera = started_capture
        camera.next_frame = None
        capture.start(REGION, target_fps=60)
        with pytest.raises(CaptureLost, match="no frame"):
            capture.get_latest_frame(timeout=2.0)

    def test_camera_exception_becomes_capture_lost(self, started_capture):
        capture, camera = started_capture
        camera.next_frame = RuntimeError("device lost")
        capture.start(REGION, target_fps=60)
        with pytest.raises(CaptureLost, match="device lost"):
            capture.get_latest_frame(timeout=2.0)

    def test_geometry_change_raises_capture_lost(self, started_capture):
        """dxcam self-heals after a resolution change with a clamped region;
        the wrong-shape frames must force a full reinit, not a distorted mirror."""
        capture, camera = started_capture
        camera.next_frame = np.zeros((1080, 2560, 3), dtype=np.uint8)  # height shrank
        capture.start(REGION, target_fps=60)
        with pytest.raises(CaptureLost, match="geometry changed"):
            capture.get_latest_frame(timeout=2.0)

    def test_stalled_capture_times_out_instead_of_blocking(self, started_capture):
        """dxcam's get_latest_frame can block forever (monitor sleep); ours can't."""
        capture, camera = started_capture
        camera.stalled = True
        capture.start(REGION, target_fps=60)
        started = time.monotonic()
        with pytest.raises(FrameUnavailable, match="no new frame within"):
            capture.get_latest_frame(timeout=0.2)
        assert time.monotonic() - started < 1.5

    def test_stall_is_not_capture_lost(self, started_capture):
        """A healthy-but-frameless capture must not trigger a rebuild.

        Rebuilding cannot fix it: dxcam's video_mode only re-emits a frame it
        already holds, so a fresh camera on a static desktop is equally empty.
        """
        capture, camera = started_capture
        camera.stalled = True
        capture.start(REGION, target_fps=60)
        with pytest.raises(FrameUnavailable):
            capture.get_latest_frame(timeout=0.05)
        assert not isinstance(FrameUnavailable("x"), CaptureLost)
        # still usable: the same camera delivers once the desktop changes again
        camera.stalled = False
        assert capture.get_latest_frame(timeout=2.0).shape == (1440, 2560, 3)

    def test_frame_unavailable_is_not_a_capture_lost_subclass(self):
        """The crux of the fix: `except CaptureLost` must not swallow a stall."""
        assert not issubclass(FrameUnavailable, CaptureLost)

    def test_health_check_sees_a_dead_reader(self, started_capture):
        """A timeout is only benign while the reader thread is still alive."""
        capture, camera = started_capture
        capture.start(REGION, target_fps=60)
        assert capture._is_healthy() is True
        camera.stopped = True  # fake returns None -> reader records failure and exits
        capture._reader.join(timeout=2.0)
        assert capture._reader.is_alive() is False
        assert capture._is_healthy() is False

    def test_not_capturing_is_capture_lost(self, started_capture):
        """dxcam reporting is_capturing=False means the device died."""
        capture, camera = started_capture
        camera.stalled = True
        camera.is_capturing = False
        capture.start(REGION, target_fps=60)
        with pytest.raises(CaptureLost, match="stopped without reporting"):
            capture.get_latest_frame(timeout=0.05)

    def test_create_returning_none_raises(self, fake_dxcam, monkeypatch):
        module, _ = fake_dxcam
        monkeypatch.setattr(module, "create", lambda **kw: None)
        with pytest.raises(CaptureLost):
            DxcamCapture(output_idx=0)

    def test_create_exception_becomes_capture_lost(self, fake_dxcam, monkeypatch):
        module, _ = fake_dxcam

        def boom(**kw):
            raise RuntimeError("no such output")

        monkeypatch.setattr(module, "create", boom)
        with pytest.raises(CaptureLost, match="no such output"):
            DxcamCapture(output_idx=9)

    def test_stop_failure_still_releases(self, started_capture, monkeypatch):
        """dxcam's factory caches unreleased cameras; skipping release() would
        hand the wedged instance right back on the next create()."""
        capture, camera = started_capture
        capture.start(REGION, target_fps=60)

        def bad_stop():
            camera.stopped = True
            raise RuntimeError("capture thread did not stop")

        monkeypatch.setattr(camera, "stop", bad_stop)
        capture.stop()  # must not raise
        assert camera.released

    def test_stop_before_start_skips_camera_stop(self, fake_dxcam):
        _, camera = fake_dxcam
        capture = DxcamCapture(output_idx=0)
        capture.stop()
        assert not camera.stopped
        assert camera.released


class TestBackendSelection:
    def test_output_info_text(self, fake_dxcam):
        assert "5120" in output_info_text()

    def test_missing_cpp_backend_suggests_extra(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "dxcam_cpp", None)  # forces ImportError
        with pytest.raises(CaptureLost, match=r"uwmirror\[cpp\]"):
            output_info_text("dxcam-cpp")
