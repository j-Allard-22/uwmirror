"""Test doubles for the capture/presentation seams."""

from __future__ import annotations

import numpy as np

from uwmirror.app import Command, LoopCommand
from uwmirror.capture import CaptureLost, FrameUnavailable
from uwmirror.geometry import Region


class FakeCapture:
    """CaptureBackend double: emits solid frames, fails on scheduled calls.

    ``frameless_on``/``frameless_from`` simulate a *healthy but frameless*
    capture — the state a real dxcam camera sits in when the source monitor has
    zero pixel changes, where video_mode has no earlier frame to re-emit.
    ``frameless_from`` makes it permanent, which is the wedge that used to send
    the loop into an endless rebuild.
    """

    def __init__(
        self,
        width: int = 5120,
        height: int = 1440,
        fail_on_frames: set[int] | None = None,
        frameless_on: set[int] | None = None,
        frameless_from: int | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.started_region: Region | None = None
        self.started_fps: int | None = None
        self.stopped = False
        self.frame_calls = 0
        self._fail_on = fail_on_frames or set()
        self._frameless_on = frameless_on or set()
        self._frameless_from = frameless_from

    def start(self, region: Region, target_fps: int) -> None:
        self.started_region = region
        self.started_fps = target_fps

    def get_latest_frame(self) -> np.ndarray:
        self.frame_calls += 1
        if self.frame_calls in self._fail_on:
            raise CaptureLost("scheduled failure")
        if self.frame_calls in self._frameless_on or (
            self._frameless_from is not None and self.frame_calls >= self._frameless_from
        ):
            raise FrameUnavailable("scheduled frameless tick")
        assert self.started_region is not None
        w, h = self.started_region.size
        return np.zeros((h, w, 3), dtype=np.uint8)

    def stop(self) -> None:
        self.stopped = True


class FakePresenter:
    """PresenterLike double recording every call."""

    def __init__(self) -> None:
        self.presented: list[tuple[int, int]] = []  # (w, h) of each presented frame
        self.blanks = 0
        self.flips = 0

    def present(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        self.presented.append((w, h))

    def blank(self) -> None:
        self.blanks += 1

    def flip(self) -> None:
        self.flips += 1


class FakeScreen:
    """Records blits from the cursor overlay."""

    def __init__(self) -> None:
        self.blits: list[tuple[int, int]] = []

    def blit(self, _sprite: object, pos: tuple[int, int]) -> None:
        self.blits.append(pos)


class ScriptedCommands:
    """Yields one scripted command batch per loop tick, then QUIT forever."""

    def __init__(self, script: list[list[LoopCommand]]) -> None:
        self._script = list(script)

    def __call__(self) -> list[LoopCommand]:
        if self._script:
            return self._script.pop(0)
        return [Command.QUIT]
