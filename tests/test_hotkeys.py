import sys

import pytest

from uwmirror.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    Hotkey,
    HotkeyAction,
    HotkeyError,
    HotkeyListener,
    parse_hotkey,
)


class TestParseHotkey:
    def test_default_pause_binding(self):
        assert parse_hotkey("ctrl+alt+p") == Hotkey(MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("P"))

    def test_all_modifiers(self):
        hotkey = parse_hotkey("ctrl+alt+shift+win+x")
        assert hotkey.modifiers == MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN | MOD_NOREPEAT

    def test_digits_and_case_insensitivity(self):
        assert parse_hotkey("Ctrl+Alt+5").vk == ord("5")
        assert parse_hotkey("CTRL+ALT+B").vk == ord("B")

    def test_function_keys(self):
        assert parse_hotkey("ctrl+f1").vk == 0x70
        assert parse_hotkey("ctrl+f24").vk == 0x87

    def test_named_keys(self):
        assert parse_hotkey("ctrl+space").vk == 0x20
        assert parse_hotkey("win+pause").vk == 0x13

    def test_whitespace_tolerated(self):
        assert parse_hotkey(" ctrl + alt + p ") == parse_hotkey("ctrl+alt+p")

    @pytest.mark.parametrize(
        "bad",
        ["p", "ctrl+", "+p", "meta+p", "ctrl+f25", "ctrl+enterkey", "", "ctrl++p"],
    )
    def test_invalid_specs_raise(self, bad):
        with pytest.raises(HotkeyError):
            parse_hotkey(bad)


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")
class TestHotkeyListener:
    def test_hotkey_message_lands_in_queue(self):
        """Deterministic: synthesize WM_HOTKEY via PostThreadMessage instead of key presses."""
        import ctypes

        from uwmirror.winapi import WM_HOTKEY

        # Obscure chord to avoid colliding with anything on a dev machine or CI.
        listener = HotkeyListener({HotkeyAction.PAUSE: parse_hotkey("ctrl+alt+shift+f13")})
        listener.start()
        try:
            assert listener._thread_id is not None
            ctypes.windll.user32.PostThreadMessageW(listener._thread_id, WM_HOTKEY, 1, 0)
            assert listener.actions.get(timeout=2.0) is HotkeyAction.PAUSE
        finally:
            listener.stop()

    def test_stop_is_idempotent_and_joins(self):
        listener = HotkeyListener({HotkeyAction.BLANK: parse_hotkey("ctrl+alt+shift+f14")})
        listener.start()
        listener.stop()
        listener.stop()  # second stop must be a no-op
        assert listener._thread is None
