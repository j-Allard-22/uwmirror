"""Tray tests: icon drawing runs for real; the controller is tested against a
fake pystray module so no real notification-area icon is created."""

import sys
import types

import pytest

from uwmirror.app import AppState, Command, SetFps
from uwmirror.config import DEFAULT_FPS, MAX_FPS
from uwmirror.tray import (
    FPS_PRESETS,
    TrayController,
    TrayUnavailable,
    draw_icon_image,
    require_tray,
)


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
    """Mimics pystray.MenuItem's constructor surface.

    Submenu handling matches the real thing: passing a Menu as the action is
    what makes an item a submenu, and pystray then neuters the item's own
    action. `checked` deliberately diverges — it is stored raw so tests can
    invoke it, where real pystray exposes it as a property that calls it.
    """

    def __init__(
        self, text, action, checked=None, radio=False, default=False, visible=True, enabled=True
    ):
        self.text = text
        self.submenu = action if isinstance(action, FakeMenu) else None
        self.action = (lambda *_a: None) if self.submenu is not None else action
        self.checked = checked
        self.radio = radio
        self.default = default
        self.visible = visible
        self.enabled = enabled


class FakeMenu:
    SEPARATOR = object()  # real pystray uses MenuItem('- - - -', None)

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


def menu_item(menu, text):
    """Look an item up by text — positional unpacking breaks on every insertion."""
    for item in menu.items:
        if getattr(item, "text", None) == text:
            return item
    raise AssertionError(f"no {text!r} in {[getattr(i, 'text', i) for i in menu.items]}")


class TestRequireTray:
    def test_missing_pystray_raises_with_extra_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pystray", None)  # forces ImportError
        with pytest.raises(TrayUnavailable, match=r"uwmirror\[tray\]"):
            require_tray()


class TestTrayController:
    def test_top_level_menu_order(self, fake_pystray):
        # Canary: an inserted entry should break exactly one obvious test.
        tray = TrayController()
        tray.start()
        texts = [getattr(i, "text", None) for i in tray._icon.menu.items]
        assert texts == ["Pause", "Blank", "Frame rate", None, "Quit"]  # None == SEPARATOR

    def test_menu_items_emit_commands(self, fake_pystray):
        tray = TrayController()
        tray.start()
        menu = tray._icon.menu
        menu_item(menu, "Pause").action(None, None)
        menu_item(menu, "Blank").action(None, None)
        menu_item(menu, "Quit").action(None, None)
        drained = [tray.actions.get_nowait() for _ in range(3)]
        assert drained == [Command.TOGGLE_PAUSE, Command.TOGGLE_BLANK, Command.QUIT]

    def test_checkmarks_reflect_pushed_state(self, fake_pystray):
        tray = TrayController()
        tray.start()
        pause = menu_item(tray._icon.menu, "Pause")
        blank = menu_item(tray._icon.menu, "Blank")
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


class TestFrameRateSubmenu:
    def fps_items(self, tray):
        submenu = menu_item(tray._icon.menu, "Frame rate").submenu
        assert submenu is not None, "Frame rate must be a submenu, not a plain item"
        return submenu.items

    def test_lists_every_preset_as_a_radio_item(self, fake_pystray):
        tray = TrayController()
        tray.start()
        items = self.fps_items(tray)
        assert [i.text for i in items] == [f"{n} fps" for n in FPS_PRESETS]
        assert all(i.radio for i in items)

    def test_items_emit_set_fps(self, fake_pystray):
        tray = TrayController()
        tray.start()
        for item in self.fps_items(tray):
            item.action(None, None)
        drained = [tray.actions.get_nowait() for _ in FPS_PRESETS]
        assert drained == [SetFps(n) for n in FPS_PRESETS]

    def test_exactly_one_is_checked_and_it_follows_state(self, fake_pystray):
        # Regression guard for closure late binding: lambdas sharing one loop
        # cell make every checkmark move as a block, so both rows below would
        # come out all-True or all-False.
        tray = TrayController()
        tray.start()
        items = self.fps_items(tray)
        assert [i.checked(None) for i in items] == [True, False, False, False]  # default 15
        tray.set_state(AppState(fps=60))
        assert [i.checked(None) for i in items] == [False, False, True, False]

    def test_a_non_preset_rate_checks_nothing(self, fake_pystray):
        tray = TrayController()
        tray.start()
        tray.set_state(AppState(fps=90))  # e.g. `uwmirror --fps 90`
        assert not any(i.checked(None) for i in self.fps_items(tray))

    def test_rate_change_refreshes_the_menu(self, fake_pystray):
        tray = TrayController()
        tray.start()
        tray.set_state(AppState(fps=120))
        assert tray._icon.menu_updates == 1

    def test_presets_are_valid_and_include_the_default(self):
        assert all(1 <= n <= MAX_FPS for n in FPS_PRESETS)
        assert DEFAULT_FPS in FPS_PRESETS  # the shipped default must be selectable
