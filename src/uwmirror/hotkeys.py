"""Global pause/blank hotkeys via RegisterHotKey — no dependencies, no admin.

The mirror window deliberately never takes focus, so window-local keys are
hard to reach; a global hotkey is the primary control. RegisterHotKey with a
NULL hwnd delivers WM_HOTKEY to the registering *thread's* message queue, so
a small daemon thread runs GetMessageW and forwards actions through a queue
the main loop drains — it cannot interfere with pygame's own event pump.

``parse_hotkey`` is pure and unit-testable; only ``HotkeyListener`` touches
the Windows API.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

# Mirrors of the Win32 MOD_* constants (kept local so parsing stays pure).
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIERS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}

_NAMED_KEYS = {
    "space": 0x20,
    "tab": 0x09,
    "esc": 0x1B,
    "pause": 0x13,
    "home": 0x24,
    "end": 0x23,
    "insert": 0x2D,
    "delete": 0x2E,
}


class HotkeyError(Exception):
    """Unparseable hotkey specification."""


class HotkeyAction(Enum):
    PAUSE = "pause"
    BLANK = "blank"
    QUIT = "quit"


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int


def parse_hotkey(spec: str) -> Hotkey:
    """Parse ``"ctrl+alt+p"``-style specs into (modifier mask, virtual key).

    Keys: single letters/digits, F1-F24, or one of the named keys
    (space, tab, esc, pause, home, end, insert, delete). At least one
    modifier is required — a bare global key would swallow normal typing.
    """
    parts = [p.strip().lower() for p in spec.split("+")]
    if len(parts) < 2 or any(not p for p in parts):
        raise HotkeyError(f"hotkey {spec!r} must be modifier(s)+key, e.g. 'ctrl+alt+p'")

    *mod_names, key = parts
    modifiers = 0
    for name in mod_names:
        if name not in _MODIFIERS:
            raise HotkeyError(f"unknown modifier {name!r} in {spec!r}")
        modifiers |= _MODIFIERS[name]

    if len(key) == 1 and (key.isascii() and (key.isalpha() or key.isdigit())):
        vk = ord(key.upper())
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        raise HotkeyError(f"unknown key {key!r} in {spec!r}")

    return Hotkey(modifiers | MOD_NOREPEAT, vk)


class HotkeyListener:
    """Daemon thread owning the RegisterHotKey registrations and message loop."""

    def __init__(self, bindings: dict[HotkeyAction, Hotkey]) -> None:
        self._bindings = bindings
        self.actions: queue.SimpleQueue[HotkeyAction] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="uwmirror-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        from uwmirror import winapi

        if self._thread_id is not None:
            winapi.post_quit_to_thread(self._thread_id)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        from uwmirror import winapi

        self._thread_id = winapi.get_current_thread_id()
        by_id: dict[int, HotkeyAction] = {}
        for hotkey_id, (action, hotkey) in enumerate(self._bindings.items(), start=1):
            if winapi.register_hotkey(hotkey_id, hotkey.modifiers, hotkey.vk):
                by_id[hotkey_id] = action
            else:
                log.warning(
                    "could not register global hotkey for %s (already in use by another app?)",
                    action.value,
                )
        self._ready.set()
        try:
            while True:
                result = winapi.wait_next_hotkey()
                if result is None:  # WM_QUIT
                    break
                if result in by_id:
                    self.actions.put(by_id[result])
        finally:
            for hotkey_id in by_id:
                winapi.unregister_hotkey(hotkey_id)
