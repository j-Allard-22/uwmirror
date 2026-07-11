"""Main loop: capture -> present, with pause/blank state and device-lost recovery.

The state transitions are a pure reducer over :class:`Command` tokens, and
``run_loop`` only sees injected callables — both are fully unit-testable.
``run`` does the real wiring (dxcam, pygame, Windows API).
"""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pygame

from uwmirror.capture import CaptureBackend, CaptureLost, Frame
from uwmirror.config import Settings
from uwmirror.geometry import Region, aspect, center_crop
from uwmirror.recovery import RetryPolicy

log = logging.getLogger(__name__)


class Command(Enum):
    QUIT = "quit"
    TOGGLE_PAUSE = "toggle_pause"
    TOGGLE_BLANK = "toggle_blank"


@dataclass(frozen=True)
class AppState:
    running: bool = True
    paused: bool = False
    blanked: bool = False


def reduce_state(state: AppState, commands: list[Command]) -> AppState:
    """Pure state transition: fold commands into a new state."""
    running, paused, blanked = state.running, state.paused, state.blanked
    for command in commands:
        if command is Command.QUIT:
            running = False
        elif command is Command.TOGGLE_PAUSE:
            paused = not paused
        elif command is Command.TOGGLE_BLANK:
            blanked = not blanked
    return AppState(running=running, paused=paused, blanked=blanked)


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
    get_commands: Callable[[], list[Command]]
    policy: RetryPolicy
    tick: Callable[[int], object]
    fps: int
    target_aspect: float


def _start_backend(deps: LoopDeps) -> tuple[CaptureBackend, Region]:
    backend = deps.backend_factory()
    region = center_crop(backend.width, backend.height, deps.target_aspect)
    try:
        backend.start(region, deps.fps)
    except CaptureLost:
        backend.stop()
        raise
    log.info(
        "capturing %dx%d region %s at %d fps",
        region.width,
        region.height,
        region.as_tuple(),
        deps.fps,
    )
    return backend, region


def run_loop(deps: LoopDeps) -> None:
    """Present frames until a QUIT command; recreate the backend when capture dies."""
    backend: CaptureBackend | None = None
    overlay: OverlayLike | None = None
    state = AppState()
    was_blanked = False

    try:
        while state.running:
            state = reduce_state(state, deps.get_commands())
            if not state.running:
                break

            if state.blanked:
                if not was_blanked:
                    deps.presenter.blank()
                    deps.presenter.flip()
                was_blanked = True
                deps.tick(deps.fps)
                continue
            was_blanked = False

            if state.paused:  # front buffer keeps the last presented frame
                deps.tick(deps.fps)
                continue

            if backend is None:
                try:
                    backend, region = _start_backend(deps)
                    overlay = deps.make_overlay(backend, region)
                except CaptureLost as exc:
                    log.warning("capture unavailable (%s); retrying", exc)
                    deps.policy.wait()
                    continue

            try:
                frame = backend.get_latest_frame()
            except CaptureLost as exc:
                log.warning("capture lost (%s); reinitializing", exc)
                backend.stop()
                backend = None
                deps.policy.wait()
                continue

            deps.policy.reset()
            deps.presenter.present(frame)
            if overlay is not None:
                overlay.draw(deps.screen)
            deps.presenter.flip()
            deps.tick(deps.fps)
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
        log.info("hotkeys: %s pause, %s blank", settings.pause_hotkey, settings.blank_hotkey)

    def get_commands() -> list[Command]:
        commands: list[Command] = []
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
            while True:
                try:
                    action = listener.actions.get_nowait()
                except queue.Empty:
                    break
                commands.append(
                    Command.TOGGLE_PAUSE if action is HotkeyAction.PAUSE else Command.TOGGLE_BLANK
                )
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
        fps=settings.fps,
        target_aspect=aspect(target_size),
    )
    try:
        run_loop(deps)
    finally:
        if listener is not None:
            listener.stop()
        presenter.close()
    return 0
