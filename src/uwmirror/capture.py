"""Capture backends: the protocol seam between the app loop and dxcam.

The dxcam import is lazy so tests (and CI, where Desktop Duplication is
unavailable) never touch it, and so ``--backend dxcam-cpp`` can swap in the
API-compatible C++ fork.

dxcam >= 0.3 recovers from device loss *internally*: after a resolution
change it silently resumes with a clamped (wrong-shape) region, and while a
monitor sleeps its ``get_latest_frame()`` blocks indefinitely. Neither may
reach the app loop — a stalled mirror must keep pumping events and a stale
crop must be recomputed. :class:`DxcamCapture` therefore consumes frames on
its own reader thread (so the app-facing call has a timeout) and validates
every frame's shape against the started region.

A wrong shape means the crop is stale, which only a rebuild fixes, so it
becomes :class:`CaptureLost`. A *timeout* does not: it means the capture is
alive but has handed us nothing yet, which a rebuild cannot fix and on a
static desktop actively makes worse (see :class:`FrameUnavailable`). The two
are reported separately.
"""

from __future__ import annotations

import importlib
import logging
import threading
from types import ModuleType
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from uwmirror.geometry import Region

log = logging.getLogger(__name__)

_BACKEND_MODULES = {"dxcam": "dxcam", "dxcam-cpp": "dxcam_cpp"}

#: Max seconds a single :meth:`DxcamCapture.get_latest_frame` call blocks before
#: handing control back to the app loop. This is a *responsiveness* bound, not a
#: health check: dxcam's own ``get_latest_frame()`` waits forever, which would
#: stop the loop pumping events (no hotkeys, no tray, no quit). Hitting it means
#: "nothing new yet" — see :class:`FrameUnavailable` — not "the device died".
FRAME_TIMEOUT = 2.0

Frame = npt.NDArray[np.uint8]


class CaptureLost(Exception):
    """The capture device died (resolution change, monitor sleep, fullscreen game).

    Recovery is always the same: stop this backend and create a fresh one.
    """


class FrameUnavailable(Exception):
    """No new frame yet, but the capture is healthy — keep showing the last one.

    Deliberately **not** a :class:`CaptureLost` subclass: rebuilding cannot fix
    this and on a fully static desktop it wedges the app into a permanent
    teardown loop. dxcam's ``video_mode`` re-emits a frame it has *already*
    captured — its ring buffer starts empty and ``reserve_duplicate_copy()``
    returns ``None`` until the first real frame — so a freshly created camera
    aimed at a monitor with zero pixel changes emits nothing at all. Recreating
    it just yields another empty buffer, which is why the old behaviour looped
    at exactly ``FRAME_TIMEOUT`` forever.

    Waiting is also simply correct: an unchanged desktop needs no repaint, and
    the running camera picks up the first real change by itself.
    """


class CaptureBackend(Protocol):
    """What the app loop needs from a screen-capture implementation."""

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def start(self, region: Region, target_fps: int) -> None: ...

    def get_latest_frame(self) -> Frame:
        """Return the newest frame.

        Raises :class:`CaptureLost` if the device needs rebuilding, or
        :class:`FrameUnavailable` if it is alive with nothing new to hand over.
        """
        ...

    def stop(self) -> None: ...


def _import_backend(name: str) -> ModuleType:
    module_name = _BACKEND_MODULES[name]
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        hint = " (install it with: pip install uwmirror[cpp])" if name == "dxcam-cpp" else ""
        raise CaptureLost(f"capture backend {name!r} is not installed{hint}: {exc}") from exc


def output_info_text(backend: str = "dxcam") -> str:
    """The raw multi-line string from ``dxcam.output_info()`` (for detect/diagnose)."""
    return str(_import_backend(backend).output_info())


def _create_camera(module: ModuleType, device_idx: int, output_idx: int) -> Any:
    # dxcam >= 0.3 defaults to a cv2 frame processor whose lazy `import cv2`
    # crashes the capture thread unless opencv-python is installed; its numpy
    # processor does the same BGRA->RGB conversion with no extra dependency.
    try:
        return module.create(
            device_idx=device_idx,
            output_idx=output_idx,
            output_color="RGB",
            processor_backend="numpy",
        )
    except TypeError:
        # dxcam-cpp and older forks don't take processor_backend
        return module.create(device_idx=device_idx, output_idx=output_idx, output_color="RGB")


class DxcamCapture:
    """dxcam/dxcam-cpp wrapper implementing :class:`CaptureBackend`.

    Always captures with ``video_mode=True`` (a static desktop must keep
    emitting frames) and crops via dxcam's ``region=`` so only the cropped
    pixels are read back from the GPU.
    """

    def __init__(self, output_idx: int, backend: str = "dxcam", device_idx: int = 0) -> None:
        module = _import_backend(backend)
        try:
            camera: Any = _create_camera(module, device_idx, output_idx)
        except Exception as exc:
            raise CaptureLost(
                f"could not create camera for device {device_idx} output {output_idx}: {exc}"
            ) from exc
        if camera is None:
            raise CaptureLost(
                f"could not create camera for device {device_idx} output {output_idx}"
            )
        self._camera = camera
        self._started = False
        self._expected_shape: tuple[int, int] | None = None
        self._latest: Frame | None = None
        self._error: str | None = None
        self._frame_ready = threading.Event()
        self._stop_reading = threading.Event()
        self._reader: threading.Thread | None = None

    @property
    def width(self) -> int:
        return int(self._camera.width)

    @property
    def height(self) -> int:
        return int(self._camera.height)

    def start(self, region: Region, target_fps: int) -> None:
        try:
            self._camera.start(region=region.as_tuple(), target_fps=target_fps, video_mode=True)
        except Exception as exc:
            raise CaptureLost(f"could not start capture: {exc}") from exc
        self._started = True
        self._expected_shape = (region.height, region.width)
        self._reader = threading.Thread(
            target=self._read_loop, name="uwmirror-capture-reader", daemon=True
        )
        self._reader.start()

    def _read_loop(self) -> None:
        """Pull frames from dxcam's blocking API into ``_latest``.

        Runs on a dedicated thread precisely because dxcam's
        ``get_latest_frame()`` can block without bound while the library
        retries device loss internally.
        """
        while not self._stop_reading.is_set():
            try:
                raw = self._camera.get_latest_frame()
            except Exception as exc:
                self._fail(f"capture device lost: {exc}")
                return
            if raw is None:
                self._fail("capture returned no frame")
                return
            frame = np.asarray(raw, dtype=np.uint8)
            if self._expected_shape is not None and frame.shape[:2] != self._expected_shape:
                # dxcam recovered from a display change on its own, with a
                # clamped region — force a full reinit so the crop is redone.
                expected_h, expected_w = self._expected_shape
                self._fail(
                    f"capture geometry changed (expected {expected_w}x{expected_h},"
                    f" got {frame.shape[1]}x{frame.shape[0]})"
                )
                return
            self._latest = frame
            self._frame_ready.set()

    def _fail(self, message: str) -> None:
        self._error = message
        self._frame_ready.set()  # wake the consumer so it sees the error

    def _is_healthy(self) -> bool:
        """Whether the capture is alive and merely has nothing new to hand over."""
        reader = self._reader
        if reader is not None and not reader.is_alive():
            return False
        # dxcam-cpp and older forks may not expose is_capturing; assume healthy
        # rather than tearing down a capture that is probably fine.
        return bool(getattr(self._camera, "is_capturing", True))

    def get_latest_frame(self, timeout: float = FRAME_TIMEOUT) -> Frame:
        if not self._frame_ready.wait(timeout):
            # _fail() sets the event, so an error here means it landed in the
            # race just after the wait expired; report it rather than lose it.
            if self._error is not None:
                raise CaptureLost(self._error)
            if self._is_healthy():
                raise FrameUnavailable(f"no new frame within {timeout:g}s")
            raise CaptureLost("capture thread stopped without reporting an error")
        if self._error is not None:
            raise CaptureLost(self._error)
        frame = self._latest
        self._frame_ready.clear()
        if frame is None:  # not reachable in practice; guards a set-without-store race
            raise CaptureLost("no frame available")
        return frame

    def stop(self) -> None:
        self._stop_reading.set()
        if self._started:
            try:
                self._camera.stop()
            except Exception:  # shutdown must never raise
                log.debug("ignoring error while stopping capture", exc_info=True)
        # Attempt release() even if stop() failed: dxcam's factory caches
        # instances per output, and an unreleased camera would be handed
        # right back to us on the next create().
        try:
            release = getattr(self._camera, "release", None)
            if callable(release):
                release()
        except Exception:
            log.debug("ignoring error while releasing capture", exc_info=True)
        self._started = False
        if self._reader is not None:
            # A reader stuck inside dxcam's internal retry loop is abandoned
            # (daemon thread); it exits once the wedged camera dies or resumes.
            self._reader.join(timeout=0.5)
            self._reader = None
