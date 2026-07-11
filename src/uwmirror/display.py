"""Presentation: a borderless pygame window on the target display.

``present()`` blits without flipping so the cursor overlay can draw on top;
callers finish the frame with ``flip()``.
"""

from __future__ import annotations

import os

import numpy as np
import pygame

from uwmirror.capture import Frame


class Presenter:
    def __init__(
        self,
        target_display: int,
        size: tuple[int, int],
        *,
        windowed: bool = False,
        scale_mode: str = "smooth",
    ) -> None:
        # SDL hint: don't activate (focus) the window when it appears.
        # Must be set before set_mode creates the window.
        os.environ.setdefault("SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN", "1")
        pygame.init()
        flags = 0 if windowed else pygame.NOFRAME
        self.size = size
        self._screen = pygame.display.set_mode(size, flags, display=target_display)
        pygame.display.set_caption("uwmirror")
        pygame.mouse.set_visible(False)
        self._scale = (
            pygame.transform.smoothscale if scale_mode == "smooth" else pygame.transform.scale
        )
        # Created on first scaled present, with the frame surface's own pixel
        # format — scale/smoothscale require source and dest to match.
        self._scale_buffer: pygame.Surface | None = None

    @property
    def screen(self) -> pygame.Surface:
        return self._screen

    @property
    def hwnd(self) -> int | None:
        """Native window handle, for SetWindowPos."""
        handle = pygame.display.get_wm_info().get("window")
        return int(handle) if handle else None

    def present(self, frame: Frame) -> None:
        """Blit an (H, W, 3) RGB frame, scaling only when sizes differ."""
        height, width = frame.shape[:2]
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)
        surface = pygame.image.frombuffer(frame, (width, height), "RGB")
        if (width, height) != self.size:
            if self._scale_buffer is None:
                self._scale_buffer = pygame.Surface(self.size, 0, surface)
            self._scale(surface, self.size, self._scale_buffer)
            self._screen.blit(self._scale_buffer, (0, 0))
        else:
            self._screen.blit(surface, (0, 0))

    def blank(self) -> None:
        self._screen.fill((0, 0, 0))

    def flip(self) -> None:
        pygame.display.flip()

    def close(self) -> None:
        pygame.quit()
