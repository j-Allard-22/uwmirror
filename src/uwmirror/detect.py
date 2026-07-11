"""Monitor detection heuristics (pure core).

dxcam output indices and pygame display indices are *independent
enumerations*; this module picks sensible defaults for both and matches
dxcam outputs to Windows monitor rectangles for the cursor overlay.
All functions are pure — callers feed in enumeration results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from uwmirror.geometry import aspect

_OUTPUT_LINE = re.compile(
    r"Device\[(?P<device>\d+)\]\s+Output\[(?P<output>\d+)\]:\s*"
    r"Res:\((?P<width>\d+),\s*(?P<height>\d+)\)\s+"
    r"Rot:(?P<rotation>\d+)\s+Primary:(?P<primary>True|False)"
)

TARGET_ASPECT_DEFAULT = 16 / 9


class DetectionError(Exception):
    """Auto-detection could not produce an unambiguous answer."""


@dataclass(frozen=True)
class OutputInfo:
    """One dxcam output as parsed from ``dxcam.output_info()``."""

    device: int
    index: int
    width: int
    height: int
    rotation: int
    primary: bool

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


@dataclass(frozen=True)
class Monitor:
    """A Windows monitor rectangle in virtual-desktop coordinates."""

    left: int
    top: int
    width: int
    height: int
    primary: bool

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


def parse_output_info(text: str) -> list[OutputInfo]:
    """Parse the human-readable string returned by ``dxcam.output_info()``."""
    outputs = [
        OutputInfo(
            device=int(m["device"]),
            index=int(m["output"]),
            width=int(m["width"]),
            height=int(m["height"]),
            rotation=int(m["rotation"]),
            primary=m["primary"] == "True",
        )
        for m in _OUTPUT_LINE.finditer(text)
    ]
    if not outputs:
        raise DetectionError(f"could not parse any outputs from dxcam output_info: {text!r}")
    return outputs


def choose_source(outputs: list[OutputInfo]) -> OutputInfo:
    """Pick the capture source: widest aspect ratio, tie-broken by primary, then index."""
    return max(outputs, key=lambda o: (aspect(o.size), o.primary, -o.index))


def find_output(outputs: list[OutputInfo], index: int) -> OutputInfo:
    """Resolve an explicit ``--source`` index to an output.

    Output indices restart per GPU device; when several devices expose the
    same index, the lowest device wins (run ``uwmirror diagnose`` to see all).
    """
    matches = sorted((o for o in outputs if o.index == index), key=lambda o: o.device)
    if not matches:
        raise DetectionError(f"no dxcam output with index {index} (see: uwmirror diagnose)")
    return matches[0]


def choose_target(desktop_sizes: list[tuple[int, int]], source_size: tuple[int, int]) -> int:
    """Pick the pygame display index to present on.

    Candidates are displays whose resolution differs from the source's;
    among them, the one closest to 16:9 wins.
    """
    if len(desktop_sizes) < 2:
        raise DetectionError(
            "only one display detected — set the TV to Extend mode in Windows"
            " Display Settings, or pass --target explicitly"
        )
    candidates = [(i, size) for i, size in enumerate(desktop_sizes) if size != tuple(source_size)]
    if not candidates:
        raise DetectionError(
            "all displays have the same resolution as the capture source;"
            " pass --source and --target explicitly (see: uwmirror diagnose)"
        )
    return min(candidates, key=lambda c: abs(aspect(c[1]) - TARGET_ASPECT_DEFAULT))[0]


def match_output_to_monitor(output: OutputInfo, monitors: list[Monitor]) -> Monitor | None:
    """Find the Windows monitor rect for a dxcam output (for cursor mapping).

    Matches by resolution, preferring an exact primary-flag match; returns
    ``None`` when the match is ambiguous or absent.
    """
    same_size = [m for m in monitors if m.size == output.size]
    exact = [m for m in same_size if m.primary == output.primary]
    pool = exact or same_size
    if len(pool) == 1:
        return pool[0]
    return None
