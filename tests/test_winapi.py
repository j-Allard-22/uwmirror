"""Smoke tests for the ctypes layer — safe, read-only calls on a real session.

These run on GitHub's windows-latest runners (which have an interactive
desktop); anything needing real capture lives in tests/integration/.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


def test_set_dpi_awareness_is_idempotent():
    from uwmirror import winapi

    winapi.set_dpi_awareness()
    winapi.set_dpi_awareness()  # second call must not raise


def test_get_cursor_pos_returns_coordinates_or_none():
    from uwmirror import winapi

    pos = winapi.get_cursor_pos()
    assert pos is None or (isinstance(pos[0], int) and isinstance(pos[1], int))


def test_is_cursor_visible_returns_bool():
    from uwmirror import winapi

    assert isinstance(winapi.is_cursor_visible(), bool)


def test_list_monitors_returns_rects():
    from uwmirror import winapi

    monitors = winapi.list_monitors()
    assert len(monitors) >= 1
    assert all(m.width > 0 and m.height > 0 for m in monitors)
    assert sum(1 for m in monitors if m.primary) == 1


def test_hotkey_register_unregister_roundtrip():
    from uwmirror import winapi

    # F15 + all modifiers: essentially guaranteed to be free.
    mods = winapi.MOD_CONTROL | winapi.MOD_ALT | winapi.MOD_SHIFT
    hotkey_id = 0x7FFF
    assert winapi.register_hotkey(hotkey_id, mods, 0x7E)
    winapi.unregister_hotkey(hotkey_id)


def test_get_current_thread_id():
    from uwmirror import winapi

    thread_id = winapi.get_current_thread_id()
    assert isinstance(thread_id, int)
    assert thread_id != 0
