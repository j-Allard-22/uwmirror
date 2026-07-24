"""System-tray control surface (pystray).

The mirror window on the TV never takes focus, so the tray icon — sitting in
the primary monitor's notification area — is the main way to pause, blank, or
quit. It runs on its own thread (pystray owns a Win32 message loop); menu
clicks are marshalled to the main loop through a queue, exactly like
:class:`~uwmirror.hotkeys.HotkeyListener`.

The optional ``pystray``/``Pillow`` dependencies are imported lazily so the
core package installs and runs without them (``pip install uwmirror[tray]``
to enable). :func:`draw_icon_image` is the single source of the icon artwork,
shared with the PyInstaller ``.ico`` generation — no binary asset in the repo.

Menu state (the Pause/Blank checkmarks and the Frame rate radio) is read from a
live snapshot the main loop pushes via :meth:`TrayController.set_state`. That
snapshot is written by the main loop's thread and read by pystray's, but it is
a single rebind of an immutable :class:`~uwmirror.app.AppState`, so a reader
sees either the old snapshot or the new one and no lock is needed.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from uwmirror.app import AppState, Command, LoopCommand, SetFps

if TYPE_CHECKING:
    from PIL import Image

log = logging.getLogger(__name__)

# Icon glyph palette: a light "monitor" with a highlighted center-crop band,
# on transparency. Readable in both light and dark notification areas.
_BEZEL = (228, 228, 232, 255)
_SCREEN = (60, 63, 70, 255)
_CROP = (94, 176, 255, 255)

#: Rates offered in the Frame rate radio submenu. Picking one applies for this
#: session only — nothing is written back to config.toml, so ``fps`` there (or
#: --fps) remains the way to change the rate the mirror starts at.
FPS_PRESETS: tuple[int, ...] = (15, 30, 60, 120)


class TrayUnavailable(Exception):
    """pystray/Pillow are not installed."""


def draw_icon_image(size: int = 64) -> Image.Image:
    """Render the tray/app icon: a monitor with a highlighted center 16:9 crop."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - covered via require_tray
        raise TrayUnavailable(str(exc)) from exc

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    unit = size / 64

    def px(*values: float) -> tuple[int, ...]:
        return tuple(round(v * unit) for v in values)

    draw.rounded_rectangle(px(6, 10, 58, 46), radius=round(4 * unit), fill=_BEZEL)
    draw.rectangle(px(10, 14, 54, 42), fill=_SCREEN)
    # center 16:9 crop band (the region uwmirror actually mirrors)
    draw.rectangle(px(22, 14, 42, 42), fill=_CROP)
    # stand
    draw.rectangle(px(28, 46, 36, 52), fill=_BEZEL)
    draw.rounded_rectangle(px(20, 52, 44, 56), radius=round(2 * unit), fill=_BEZEL)
    return img


def require_tray() -> Any:
    """Import pystray or raise :class:`TrayUnavailable` with an install hint."""
    try:
        import pystray
    except ImportError as exc:
        raise TrayUnavailable(
            f"system tray needs pystray/Pillow (install with: pip install uwmirror[tray]): {exc}"
        ) from exc
    return pystray


class TrayController:
    """Owns the pystray icon; emits :class:`Command`\\ s onto :attr:`actions`."""

    # pystray runs its icon on a non-daemon thread and its stop() is a no-op
    # until the icon has finished initializing. start() blocks until then so a
    # later stop() can't leave that thread alive and hang process exit.
    READY_TIMEOUT = 5.0

    def __init__(self) -> None:
        self.actions: queue.SimpleQueue[LoopCommand] = queue.SimpleQueue()
        self._state = AppState()
        self._icon: Any | None = None

    def set_state(self, state: AppState) -> None:
        """Push the latest app state so the menu checkmarks stay accurate."""
        changed = state != self._state
        self._state = state
        if changed and self._icon is not None:
            try:
                self._icon.update_menu()
            except Exception:  # pragma: no cover - backend-specific, non-fatal
                log.debug("tray update_menu failed", exc_info=True)

    def start(self) -> None:
        """Create the icon and run it on a background thread.

        Raises :class:`TrayUnavailable` if pystray/Pillow are missing.
        """
        pystray = require_tray()
        menu = pystray.Menu(
            pystray.MenuItem(
                "Pause", self._on(Command.TOGGLE_PAUSE), checked=lambda _i: self._state.paused
            ),
            pystray.MenuItem(
                "Blank", self._on(Command.TOGGLE_BLANK), checked=lambda _i: self._state.blanked
            ),
            pystray.MenuItem("Frame rate", self._fps_menu(pystray)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on(Command.QUIT)),
        )
        self._icon = pystray.Icon("uwmirror", icon=draw_icon_image(), title="uwmirror", menu=menu)
        # run_detached spins pystray's message loop on its own thread. The setup
        # callback fires only after pystray marks the icon running, so waiting on
        # it guarantees a subsequent stop() actually stops the thread.
        ready = threading.Event()

        def _on_ready(icon: Any) -> None:
            icon.visible = True  # required when a custom setup callback is given
            ready.set()

        self._icon.run_detached(setup=_on_ready)
        if not ready.wait(self.READY_TIMEOUT):
            log.warning(
                "system tray icon did not finish initializing within %.0fs", self.READY_TIMEOUT
            )

    def _fps_menu(self, pystray: Any) -> Any:
        """Radio submenu of the frame-rate presets.

        Passing a ``Menu`` as an item's action is what makes pystray treat it
        as a submenu; the parent item itself becomes inert. ``radio=True`` only
        takes effect alongside a ``checked`` callable, and Win32 does not
        enforce mutual exclusion — the callables are the only thing keeping
        exactly one preset lit.
        """
        return pystray.Menu(
            *(
                pystray.MenuItem(
                    f"{fps} fps", self._on(SetFps(fps)), checked=self._is_fps(fps), radio=True
                )
                for fps in FPS_PRESETS
            )
        )

    def _is_fps(self, fps: int) -> Callable[[Any], bool]:
        """Build a checked-predicate bound to *fps*.

        Deliberately a factory: an inline ``lambda _item: self._state.fps ==
        fps`` inside the generator above would close over the generator's
        single loop cell, so every preset would compare against the last one
        and all four checkmarks would move as a block.
        """
        return lambda _item: self._state.fps == fps

    def _on(self, command: LoopCommand) -> Any:
        def handler(_icon: Any, _item: Any) -> None:
            self.actions.put(command)

        return handler

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # pragma: no cover - shutdown must never raise
                log.debug("tray stop failed", exc_info=True)
            self._icon = None
