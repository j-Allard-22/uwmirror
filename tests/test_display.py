"""Presenter tests run real pygame under SDL's dummy video driver."""

import numpy as np
import pytest

from uwmirror.display import Presenter


@pytest.fixture
def presenter():
    p = Presenter(0, (320, 180), windowed=True)
    yield p
    p.close()


def frame(width: int, height: int, value: int = 128) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


class TestPresenter:
    def test_present_matching_size_is_a_pure_blit(self, presenter: Presenter):
        presenter.present(frame(320, 180, value=200))
        presenter.flip()
        assert presenter.screen.get_at((0, 0))[:3] == (200, 200, 200)

    def test_present_larger_frame_downscales(self, presenter: Presenter):
        presenter.present(frame(640, 360, value=90))
        presenter.flip()
        assert presenter.screen.get_size() == (320, 180)
        assert presenter.screen.get_at((160, 90))[:3] == (90, 90, 90)

    def test_fast_scale_mode(self):
        p = Presenter(0, (320, 180), windowed=True, scale_mode="fast")
        try:
            p.present(frame(640, 360, value=60))
            assert p.screen.get_at((10, 10))[:3] == (60, 60, 60)
        finally:
            p.close()

    def test_non_contiguous_frame_is_handled(self, presenter: Presenter):
        wide = np.full((180, 640, 3), 33, dtype=np.uint8)
        view = wide[:, ::2, :]  # non-contiguous view, shape (180, 320, 3)
        assert not view.flags["C_CONTIGUOUS"]
        presenter.present(view)
        assert presenter.screen.get_at((5, 5))[:3] == (33, 33, 33)

    def test_blank_paints_black(self, presenter: Presenter):
        presenter.present(frame(320, 180, value=255))
        presenter.blank()
        presenter.flip()
        assert presenter.screen.get_at((100, 100))[:3] == (0, 0, 0)

    def test_hwnd_is_int_or_none(self, presenter: Presenter):
        assert presenter.hwnd is None or isinstance(presenter.hwnd, int)
