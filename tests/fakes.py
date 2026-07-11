"""Test doubles for the capture/presentation seams."""

from __future__ import annotations

import numpy as np

from uwmirror.app import Command
from uwmirror.capture import CaptureLost
from uwmirror.geometry import Region


class FakeCapture:
    """CaptureBackend double: emits solid frames, fails on scheduled calls."""

    def __init__(
        self,
        width: int = 5120,
        height: int = 1440,
        fail_on_frames: set[int] | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.started_region: Region | None = None
        self.started_fps: int | None = None
        self.stopped = False
        self.frame_calls = 0
        self._fail_on = fail_on_frames or set()

    def start(self, region: Region, target_fps: int) -> None:
        self.started_region = region
        self.started_fps = target_fps

    def get_latest_frame(self) -> np.ndarray:
        self.frame_calls += 1
        if self.frame_calls in self._fail_on:
            raise CaptureLost("scheduled failure")
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

    def __init__(self, script: list[list[Command]]) -> None:
        self._script = list(script)

    def __call__(self) -> list[Command]:
        if self._script:
            return self._script.pop(0)
        return [Command.QUIT]
