"""Pure geometry: crop regions, aspect math, and coordinate mapping.

No I/O and no Windows/pygame imports — everything here is unit-testable anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    """A source-pixel rectangle, dxcam-style: (left, top, right, bottom), right/bottom exclusive."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


def aspect(size: tuple[int, int]) -> float:
    """Width/height ratio of a (w, h) size."""
    width, height = size
    if height <= 0:
        raise ValueError(f"invalid size {size!r}")
    return width / height


def center_crop(width: int, height: int, target_aspect: float) -> Region:
    """Largest centered region of ``width``x``height`` matching ``target_aspect`` (w/h).

    For a source wider than the target aspect this is a full-height crop
    (the ultrawide case: 5120x1440 @ 16:9 -> 2560x1440); for a narrower
    source it is a full-width crop with reduced height.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid source size {width}x{height}")
    if target_aspect <= 0:
        raise ValueError(f"invalid target aspect {target_aspect}")

    crop_w = round(height * target_aspect)
    if crop_w <= width:
        left = (width - crop_w) // 2
        return Region(left, 0, left + crop_w, height)

    crop_h = round(width / target_aspect)
    top = (height - crop_h) // 2
    return Region(0, top, width, top + crop_h)


def map_point(
    point: tuple[int, int], region: Region, target_size: tuple[int, int]
) -> tuple[int, int] | None:
    """Map a source-monitor point into target-window coordinates.

    ``point`` is relative to the captured monitor's top-left. Returns the
    scaled position inside a ``target_size`` window showing ``region``, or
    ``None`` when the point falls outside the crop.
    """
    x, y = point
    if not region.contains(x, y):
        return None
    scale_x = target_size[0] / region.width
    scale_y = target_size[1] / region.height
    return (round((x - region.left) * scale_x), round((y - region.top) * scale_y))
