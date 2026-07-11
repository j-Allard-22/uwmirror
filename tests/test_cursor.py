import pygame
import pytest
from fakes import FakeScreen

from uwmirror.cursor import CursorOverlay, make_arrow_surface
from uwmirror.detect import Monitor
from uwmirror.geometry import Region

MONITOR = Monitor(0, 0, 5120, 1440, primary=True)
REGION = Region(1280, 0, 3840, 1440)
TARGET = (1920, 1080)


@pytest.fixture(autouse=True)
def _pygame():
    pygame.init()
    yield
    pygame.quit()


def make_overlay(pos, visible=True):
    return CursorOverlay(
        MONITOR,
        REGION,
        TARGET,
        pos_provider=lambda: pos,
        visible_provider=lambda: visible,
    )


class TestArrowSprite:
    def test_has_transparent_background_and_opaque_body(self):
        sprite = make_arrow_surface(24)
        assert sprite.get_size() == (24, 24)
        assert sprite.get_at((23, 0)).a == 0  # top-right corner is empty
        assert sprite.get_at((2, 6)).a == 255  # inside the arrow shaft

    def test_minimum_size_clamped(self):
        assert make_arrow_surface(2).get_size() == (8, 8)


class TestCursorOverlay:
    def test_blits_at_mapped_position(self):
        screen = FakeScreen()
        # (2560, 720) is 1280 px into the 2560-wide crop; 2560->1920 scales by 0.75
        make_overlay(pos=(2560, 720)).draw(screen)
        assert screen.blits == [(960, 540)]

    def test_outside_crop_is_skipped(self):
        screen = FakeScreen()
        make_overlay(pos=(100, 100)).draw(screen)  # in the left pillar, outside the crop
        assert screen.blits == []

    def test_hidden_cursor_is_skipped(self):
        screen = FakeScreen()
        make_overlay(pos=(2560, 720), visible=False).draw(screen)
        assert screen.blits == []

    def test_unavailable_position_is_skipped(self):
        screen = FakeScreen()
        make_overlay(pos=None).draw(screen)
        assert screen.blits == []

    def test_monitor_origin_offset_is_applied(self):
        monitor = Monitor(-5120, 0, 5120, 1440, primary=False)  # left of primary
        screen = FakeScreen()
        overlay = CursorOverlay(
            monitor,
            REGION,
            TARGET,
            pos_provider=lambda: (-2560, 720),  # center of that monitor
            visible_provider=lambda: True,
        )
        overlay.draw(screen)
        assert screen.blits == [(960, 540)]

    def test_sprite_scales_with_target_ratio(self):
        overlay = make_overlay(pos=(2560, 720))
        # 1080/1440 = 0.75 -> 24 * 0.75 = 18
        assert overlay._sprite.get_size() == (18, 18)
