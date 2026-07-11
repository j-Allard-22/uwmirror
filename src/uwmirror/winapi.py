"""All ctypes Windows API calls live here — the only module that touches user32/shcore.

Private ``WinDLL`` instances carry explicit ``argtypes``/``restype`` so 64-bit
handles are never truncated through ctypes' default c_int marshalling (and so
our prototypes can't clash with other libraries using ``ctypes.windll``).

Import this module only after checking ``sys.platform == "win32"``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging

from uwmirror.detect import Monitor

log = logging.getLogger(__name__)

# SetWindowPos
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

# GetCursorInfo
CURSOR_SHOWING = 0x0001

# RegisterHotKey modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MONITORINFOF_PRIMARY = 0x0001


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", wintypes.POINT),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
_user32.GetCursorInfo.restype = wintypes.BOOL
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    _MonitorEnumProc,
    wintypes.LPARAM,
]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
_user32.GetMessageW.restype = ctypes.c_int  # BOOL, but -1 on error
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def set_dpi_awareness() -> None:
    """Opt in to per-monitor DPI awareness. MUST run before pygame initializes.

    Failure is non-fatal (already set via manifest, or pre-8.1 Windows).
    """
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except OSError:  # pragma: no cover - depends on process state
        log.debug("SetProcessDpiAwareness failed (may already be set)", exc_info=True)


def get_cursor_pos() -> tuple[int, int] | None:
    """Cursor position in virtual-desktop (physical pixel) coordinates."""
    point = wintypes.POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        return None
    return (point.x, point.y)


def is_cursor_visible() -> bool:
    """Whether the system cursor is currently shown (apps can hide it)."""
    info = _CURSORINFO()
    info.cbSize = ctypes.sizeof(_CURSORINFO)
    if not _user32.GetCursorInfo(ctypes.byref(info)):
        return True  # assume visible if the call fails
    return bool(info.flags & CURSOR_SHOWING)


def list_monitors() -> list[Monitor]:
    """Enumerate monitor rectangles in virtual-desktop coordinates."""
    monitors: list[Monitor] = []

    def _callback(
        hmonitor: int | None,
        _hdc: int | None,
        _rect: ctypes._Pointer[wintypes.RECT],
        _lparam: int,
    ) -> int:
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rc = info.rcMonitor
            monitors.append(
                Monitor(
                    left=rc.left,
                    top=rc.top,
                    width=rc.right - rc.left,
                    height=rc.bottom - rc.top,
                    primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                )
            )
        return 1  # continue enumeration

    _user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_callback), 0)
    return monitors


def set_topmost_noactivate(hwnd: int) -> None:
    """Keep the window above others without letting it steal focus."""
    _user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def register_hotkey(hotkey_id: int, modifiers: int, vk: int) -> bool:
    """Register a global hotkey on the *calling thread's* message queue."""
    return bool(_user32.RegisterHotKey(None, hotkey_id, modifiers, vk))


def unregister_hotkey(hotkey_id: int) -> None:
    _user32.UnregisterHotKey(None, hotkey_id)


def get_current_thread_id() -> int:
    return int(_kernel32.GetCurrentThreadId())


def post_quit_to_thread(thread_id: int) -> None:
    """Break a thread out of its GetMessageW loop."""
    _user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)


def wait_next_hotkey() -> int | None:
    """Block on GetMessageW; return the hotkey id, or ``None`` on WM_QUIT/error."""
    msg = wintypes.MSG()
    result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
    if result <= 0:  # 0 = WM_QUIT, -1 = error
        return None
    if msg.message == WM_HOTKEY:
        return int(msg.wParam)
    return -1  # unrelated message; caller loops
