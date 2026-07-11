"""Cursor overlay: Desktop Duplication never captures the mouse, so draw one.

The sprite is a classic arrow drawn programmatically (no binary assets in
the repo). Position providers are injectable for tests; the defaults read
the real cursor via the Windows API.
"""

from __future__ import annotations

from collections.abc import Callable

import pygame

from uwmirror.detect import Monitor
from uwmirror.geometry import Region, map_point

BASE_HEIGHT = 24  # sprite height in pixels before crop->target scaling

# Arrow outline in a 0..1 unit square (x, y), tip at the origin.
_ARROW = [
    (0.00, 0.00),
    (0.00, 0.83),
    (0.21, 0.66),
    (0.34, 0.96),
    (0.45, 0.92),
    (0.32, 0.62),
    (0.60, 0.60),
]


def make_arrow_surface(height: int = BASE_HEIGHT) -> pygame.Surface:
    """A white arrow with a black outline on a transparent surface."""
    height = max(height, 8)
    surface = pygame.Surface((height, height), pygame.SRCALPHA)
    points = [(x * (height - 1), y * (height - 1)) for x, y in _ARROW]
    pygame.draw.polygon(surface, (255, 255, 255), points)
    pygame.draw.polygon(surface, (0, 0, 0), points, width=2)
    return surface


class CursorOverlay:
    """Maps the real cursor into the mirrored crop and blits a sprite there."""

    def __init__(
        self,
        monitor: Monitor,
        region: Region,
        target_size: tuple[int, int],
        *,
        pos_provider: Callable[[], tuple[int, int] | None] | None = None,
        visible_provider: Callable[[], bool] | None = None,
    ) -> None:
        if pos_provider is None or visible_provider is None:
            from uwmirror import winapi  # deferred: keeps this module importable in tests

            pos_provider = pos_provider or winapi.get_cursor_pos
            visible_provider = visible_provider or winapi.is_cursor_visible
        self._monitor = monitor
        self._region = region
        self._target_size = target_size
        self._pos = pos_provider
        self._visible = visible_provider
        scale = target_size[1] / region.height
        self._sprite = make_arrow_surface(round(BASE_HEIGHT * scale))

    def draw(self, screen: pygame.Surface) -> None:
        """Blit the cursor sprite if the cursor is visible and inside the crop."""
        if not self._visible():
            return
        pos = self._pos()
        if pos is None:
            return
        local = (pos[0] - self._monitor.left, pos[1] - self._monitor.top)
        mapped = map_point(local, self._region, self._target_size)
        if mapped is None:
            return
        screen.blit(self._sprite, mapped)
