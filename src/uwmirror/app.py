"""Main loop: capture -> present, with pause/blank state and device-lost recovery.

The state transitions are a pure reducer over :class:`Command` tokens, and
``run_loop`` only sees injected callables — both are fully unit-testable.
``run`` does the real wiring (dxcam, pygame, Windows API).
"""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import pygame

    from uwmirror.hotkeys import HotkeyAction
    from uwmirror.tray import TrayController

from uwmirror.capture import CaptureBackend, CaptureLost, Frame, FrameUnavailable
from uwmirror.config import DEFAULT_FPS, Settings
from uwmirror.geometry import Region, aspect, center_crop
from uwmirror.recovery import RetryPolicy

log = logging.getLogger(__name__)


class Command(Enum):
    QUIT = "quit"
    TOGGLE_PAUSE = "toggle_pause"
    TOGGLE_BLANK = "toggle_blank"


@dataclass(frozen=True)
class SetFps:
    """Set the capture/present rate for this session (never persisted)."""

    value: int


#: Everything the loop accepts on its command channel.
LoopCommand = Command | SetFps


@dataclass(frozen=True)
class AppState:
    running: bool = True
    paused: bool = False
    blanked: bool = False
    fps: int = DEFAULT_FPS


def reduce_state(state: AppState, commands: Sequence[LoopCommand]) -> AppState:
    """Pure state transition: fold commands into a new state.

    Built by folding ``replace`` rather than rebuilding ``AppState`` field by
    field, so a field added here later cannot be silently dropped back to its
    default by a command that does not mention it.
    """
    for command in commands:
        if isinstance(command, SetFps):
            state = replace(state, fps=command.value)
        elif command is Command.QUIT:
            state = replace(state, running=False)
        elif command is Command.TOGGLE_PAUSE:
            state = replace(state, paused=not state.paused)
        elif command is Command.TOGGLE_BLANK:
            state = replace(state, blanked=not state.blanked)
    return state


class PresenterLike(Protocol):
    """What the loop needs from the presentation layer."""

    def present(self, frame: Frame) -> None: ...

    def blank(self) -> None: ...

    def flip(self) -> None: ...


class OverlayLike(Protocol):
    def draw(self, screen: pygame.Surface) -> None: ...


@dataclass
class LoopDeps:
    """Everything ``run_loop`` needs, injectable for tests."""

    backend_factory: Callable[[], CaptureBackend]
    presenter: PresenterLike
    screen: pygame.Surface
    make_overlay: Callable[[CaptureBackend, Region], OverlayLike | None]
    get_commands: Callable[[], list[LoopCommand]]
    policy: RetryPolicy
    tick: Callable[[int], object]
    #: Seed for ``AppState.fps`` only — the loop reads ``state.fps`` thereafter.
    initial_fps: int
    target_aspect: float
    on_state: Callable[[AppState], None] | None = None


def _drain(
    source: queue.SimpleQueue[Any],
    commands: list[LoopCommand],
    mapping: dict[HotkeyAction, Command] | None = None,
) -> None:
    """Move every queued item into ``commands``, mapping actions to commands."""
    while True:
        try:
            item = source.get_nowait()
        except queue.Empty:
            break
        commands.append(mapping[item] if mapping is not None else item)


def _start_tray(settings: Settings) -> TrayController | None:
    """Start the system-tray controller, or return ``None`` if disabled/absent."""
    if not settings.tray:
        return None
    from uwmirror.tray import TrayController, TrayUnavailable

    try:
        tray = TrayController()
        tray.start()
    except TrayUnavailable as exc:
        log.info("system tray unavailable (%s); use the hotkeys instead", exc)
        return None
    except Exception:
        # The tray is a convenience, never essential (the quit hotkey always
        # works); a failure here must not take down the mirror or leak the
        # already-started presenter/hotkey listener.
        log.warning("system tray failed to start; use the hotkeys instead", exc_info=True)
        return None
    log.info("system tray active (right-click the icon for pause/blank/quit)")
    return tray


def _start_backend(deps: LoopDeps, fps: int) -> tuple[CaptureBackend, Region]:
    backend = deps.backend_factory()
    region = center_crop(backend.width, backend.height, deps.target_aspect)
    try:
        backend.start(region, fps)
    except CaptureLost:
        backend.stop()
        raise
    log.info(
        "capturing %dx%d region %s at %d fps",
        region.width,
        region.height,
        region.as_tuple(),
        fps,
    )
    return backend, region


def run_loop(deps: LoopDeps) -> None:
    """Present frames until a QUIT command; recreate the backend when capture dies."""
    backend: CaptureBackend | None = None
    backend_fps: int | None = None  # rate the live backend was started with
    overlay: OverlayLike | None = None
    state = AppState(fps=deps.initial_fps)
    was_blanked = False
    frameless = False  # logged once per stall, not every FRAME_TIMEOUT
    if deps.on_state is not None:
        deps.on_state(state)

    try:
        while state.running:
            previous = state
            state = reduce_state(state, deps.get_commands())
            if deps.on_state is not None and state != previous:
                deps.on_state(state)
            if not state.running:
                break

            if state.blanked:
                if not was_blanked:
                    deps.presenter.blank()
                    deps.presenter.flip()
                was_blanked = True
                deps.tick(state.fps)
                continue
            was_blanked = False

            if state.paused:  # front buffer keeps the last presented frame
                deps.tick(state.fps)
                continue

            # dxcam bakes target_fps into camera.start() and exposes no setter,
            # so a rate change reuses the device-lost path: drop the backend and
            # let the block below recreate it with a freshly recomputed crop.
            if backend is not None and backend_fps != state.fps:
                log.info("frame rate changed to %d fps; restarting capture", state.fps)
                backend.stop()
                backend = None

            if backend is None:
                try:
                    backend, region = _start_backend(deps, state.fps)
                    backend_fps = state.fps
                    overlay = deps.make_overlay(backend, region)
                except CaptureLost as exc:
                    log.warning("capture unavailable (%s); retrying", exc)
                    deps.policy.wait()
                    continue

            try:
                frame = backend.get_latest_frame()
            except FrameUnavailable:
                # Alive, just nothing new: hold the last presented frame. A
                # rebuild cannot conjure a frame dxcam has no source for, and
                # on a static desktop it loops forever (see FrameUnavailable).
                if not frameless:
                    log.info("no new frames (static desktop or display asleep); holding last frame")
                    frameless = True
                deps.tick(state.fps)
                continue
            except CaptureLost as exc:
                log.warning("capture lost (%s); reinitializing", exc)
                backend.stop()
                backend = None
                deps.policy.wait()
                continue

            if frameless:
                log.info("frames resumed")
                frameless = False
            deps.policy.reset()
            deps.presenter.present(frame)
            if overlay is not None:
                overlay.draw(deps.screen)
            deps.presenter.flip()
            deps.tick(state.fps)
    finally:
        if backend is not None:
            backend.stop()


def run(settings: Settings) -> int:
    """Wire up the real capture, presentation, cursor, and hotkeys, then loop."""
    import pygame

    from uwmirror import detect, winapi
    from uwmirror.capture import DxcamCapture, output_info_text
    from uwmirror.cursor import CursorOverlay
    from uwmirror.display import Presenter
    from uwmirror.hotkeys import HotkeyAction, HotkeyListener, parse_hotkey

    hotkey_bindings = {
        HotkeyAction.PAUSE: parse_hotkey(settings.pause_hotkey),
        HotkeyAction.BLANK: parse_hotkey(settings.blank_hotkey),
        HotkeyAction.QUIT: parse_hotkey(settings.quit_hotkey),
    }
    action_command = {
        HotkeyAction.PAUSE: Command.TOGGLE_PAUSE,
        HotkeyAction.BLANK: Command.TOGGLE_BLANK,
        HotkeyAction.QUIT: Command.QUIT,
    }

    outputs = detect.parse_output_info(output_info_text(settings.backend))
    if settings.source is not None:
        source = detect.find_output(outputs, settings.source)
    else:
        source = detect.choose_source(outputs)
    log.info(
        "source: dxcam device %d output %d (%dx%d)",
        source.device,
        source.index,
        source.width,
        source.height,
    )

    pygame.init()
    desktop_sizes = pygame.display.get_desktop_sizes()
    if settings.target is not None:
        if not 0 <= settings.target < len(desktop_sizes):
            raise detect.DetectionError(
                f"no display with index {settings.target};"
                f" pygame sees {len(desktop_sizes)} display(s) (see: uwmirror diagnose)"
            )
        target = settings.target
    else:
        target = detect.choose_target(desktop_sizes, source.size)
    target_size = desktop_sizes[target]
    log.info("target: display %d (%dx%d)", target, target_size[0], target_size[1])

    window_size = (target_size[0] // 2, target_size[1] // 2) if settings.windowed else target_size
    presenter = Presenter(
        target, window_size, windowed=settings.windowed, scale_mode=settings.scale
    )
    if settings.topmost and not settings.windowed and presenter.hwnd:
        winapi.set_topmost_noactivate(presenter.hwnd)

    def make_overlay(backend: CaptureBackend, region: Region) -> CursorOverlay | None:
        """Build the overlay against *current* monitor geometry.

        Called on every backend (re)start: after a resolution change the
        startup monitor rects are stale, so they are re-enumerated here.
        """
        if not settings.cursor:
            return None
        current = replace(source, width=backend.width, height=backend.height)
        monitor = detect.match_output_to_monitor(current, winapi.list_monitors())
        if monitor is None:
            log.warning("could not match the capture output to a monitor; cursor overlay off")
            return None
        return CursorOverlay(monitor, region, presenter.size)

    listener: HotkeyListener | None = None
    if settings.hotkeys:
        listener = HotkeyListener(hotkey_bindings)
        listener.start()
        log.info(
            "hotkeys: %s pause, %s blank, %s quit",
            settings.pause_hotkey,
            settings.blank_hotkey,
            settings.quit_hotkey,
        )

    tray = _start_tray(settings)

    def get_commands() -> list[LoopCommand]:
        commands: list[LoopCommand] = []
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                commands.append(Command.QUIT)
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    commands.append(Command.QUIT)
                elif event.key == pygame.K_SPACE:
                    commands.append(Command.TOGGLE_PAUSE)
                elif event.key == pygame.K_b:
                    commands.append(Command.TOGGLE_BLANK)
        if listener is not None:
            _drain(listener.actions, commands, action_command)
        if tray is not None:
            _drain(tray.actions, commands)
        return commands

    clock = pygame.time.Clock()
    deps = LoopDeps(
        backend_factory=lambda: DxcamCapture(
            source.index, settings.backend, device_idx=source.device
        ),
        presenter=presenter,
        screen=presenter.screen,
        make_overlay=make_overlay,
        get_commands=get_commands,
        policy=RetryPolicy(),
        tick=clock.tick,
        initial_fps=settings.fps,
        target_aspect=aspect(target_size),
        on_state=(tray.set_state if tray is not None else None),
    )
    try:
        run_loop(deps)
    finally:
        if tray is not None:
            tray.stop()
        if listener is not None:
            listener.stop()
        presenter.close()
    return 0
