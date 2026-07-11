"""Live smoke tests: real Desktop Duplication on a real desktop.

Run manually on a dev machine:  pytest -m local_display --no-cov
These are excluded by default (and would fail on CI, where DXGI capture
returns blank frames or errors).
"""

import pytest

pytestmark = pytest.mark.local_display


def test_dxcam_captures_a_center_crop_frame():
    from uwmirror.capture import DxcamCapture, output_info_text
    from uwmirror.detect import choose_source, parse_output_info
    from uwmirror.geometry import center_crop

    source = choose_source(parse_output_info(output_info_text()))
    backend = DxcamCapture(source.index)
    try:
        region = center_crop(backend.width, backend.height, 16 / 9)
        backend.start(region, target_fps=30)
        frame = backend.get_latest_frame()
        assert frame.shape == (region.height, region.width, 3)
    finally:
        backend.stop()


def test_diagnose_runs_against_real_hardware(capsys):
    from uwmirror import diagnose

    assert diagnose.run() == 0
    out = capsys.readouterr().out
    assert "dxcam outputs" in out
    assert "pygame displays" in out
