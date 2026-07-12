"""Tray tests: icon drawing runs for real; the controller is tested against a
fake pystray module so no real notification-area icon is created."""

import sys
import types

import pytest

from uwmirror.app import AppState, Command
from uwmirror.tray import TrayController, TrayUnavailable, draw_icon_image, require_tray


class TestDrawIcon:
    def test_produces_rgba_image_of_requested_size(self):
        img = draw_icon_image(48)
        assert img.size == (48, 48)
        assert img.mode == "RGBA"

    def test_has_transparent_corners_and_opaque_body(self):
        img = draw_icon_image(64)
        assert img.getpixel((0, 0))[3] == 0  # transparent corner
        assert img.getpixel((32, 28))[3] == 255  # opaque screen area


class FakeIcon:
    """Mimics the surface of pystray.Icon that TrayController touches."""

    def __init__(self, name, icon=None, title=None, menu=None):
        self.name = name
        self.menu = menu
        self.running = False
        self.menu_updates = 0

    def run_detached(self, setup=None):
        self.running = True
        self.visible = False
        if setup is not None:  # pystray calls setup once the icon is ready
            setup(self)

    def update_menu(self):
        self.menu_updates += 1

    def stop(self):
        self.running = False


class FakeMenuItem:
    def __init__(self, text, action, checked=None):
        self.text = text
        self.action = action
        self.checked = checked


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


@pytest.fixture
def fake_pystray(monkeypatch: pytest.MonkeyPatch):
    module = types.ModuleType("pystray")
    module.Icon = FakeIcon
    module.MenuItem = FakeMenuItem
    module.Menu = FakeMenu
    monkeypatch.setitem(sys.modules, "pystray", module)
    return module


class TestRequireTray:
    def test_missing_pystray_raises_with_extra_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pystray", None)  # forces ImportError
        with pytest.raises(TrayUnavailable, match=r"uwmirror\[tray\]"):
            require_tray()


class TestTrayController:
    def test_menu_items_emit_commands(self, fake_pystray):
        tray = TrayController()
        tray.start()
        items = tray._icon.menu.items
        # items: Pause, Blank, SEPARATOR, Quit
        pause, blank, _sep, quit_item = items
        pause.action(None, None)
        blank.action(None, None)
        quit_item.action(None, None)
        drained = [tray.actions.get_nowait() for _ in range(3)]
        assert drained == [Command.TOGGLE_PAUSE, Command.TOGGLE_BLANK, Command.QUIT]

    def test_checkmarks_reflect_pushed_state(self, fake_pystray):
        tray = TrayController()
        tray.start()
        pause, blank, _sep, _quit = tray._icon.menu.items
        assert pause.checked(None) is False
        tray.set_state(AppState(paused=True, blanked=True))
        assert pause.checked(None) is True
        assert blank.checked(None) is True

    def test_set_state_refreshes_menu_only_on_change(self, fake_pystray):
        tray = TrayController()
        tray.start()
        icon = tray._icon
        tray.set_state(AppState(paused=True))
        assert icon.menu_updates == 1
        tray.set_state(AppState(paused=True))  # no change
        assert icon.menu_updates == 1

    def test_run_detached_is_used(self, fake_pystray):
        tray = TrayController()
        tray.start()
        assert tray._icon.running is True

    def test_start_waits_for_ready_and_makes_icon_visible(self, fake_pystray):
        # FakeIcon invokes the setup callback synchronously, so start() returns
        # only once the icon is marked ready+visible — the guard against a
        # stop() no-op that would orphan pystray's non-daemon thread.
        tray = TrayController()
        tray.start()
        assert tray._icon.visible is True

    def test_stop_is_idempotent(self, fake_pystray):
        tray = TrayController()
        tray.start()
        tray.stop()
        tray.stop()  # must not raise
        assert tray._icon is None

    def test_set_state_before_start_is_safe(self, fake_pystray):
        tray = TrayController()
        tray.set_state(AppState(paused=True))  # no icon yet; must not raise
