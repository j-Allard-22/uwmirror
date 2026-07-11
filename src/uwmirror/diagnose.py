"""``uwmirror diagnose`` — show both display enumerations and the chosen defaults.

dxcam outputs and pygame displays are independently numbered; this report
puts them side by side, explains what auto-detection would pick, and prints
a ready-to-paste config.toml pinning those choices.
"""

from __future__ import annotations

from uwmirror import detect
from uwmirror.geometry import aspect


def format_report(
    outputs: list[detect.OutputInfo],
    desktop_sizes: list[tuple[int, int]],
    monitors: list[detect.Monitor],
) -> str:
    lines: list[str] = []

    multi_device = len({out.device for out in outputs}) > 1
    lines.append("dxcam outputs (use with --source):")
    for out in outputs:
        primary = " primary" if out.primary else ""
        device = f" (device {out.device})" if multi_device else ""
        res = f"{out.width}x{out.height} (aspect {aspect(out.size):.2f})"
        lines.append(f"  [{out.index}] {res}{primary}{device}")

    lines.append("")
    lines.append("pygame displays (use with --target):")
    for i, size in enumerate(desktop_sizes):
        lines.append(f"  [{i}] {size[0]}x{size[1]} (aspect {aspect(size):.2f})")

    lines.append("")
    lines.append("Windows monitors (virtual-desktop rects):")
    for mon in monitors:
        primary = " primary" if mon.primary else ""
        lines.append(f"  ({mon.left}, {mon.top}) {mon.width}x{mon.height}{primary}")

    lines.append("")
    try:
        source = detect.choose_source(outputs)
        lines.append(
            f"auto-detected source: output {source.index}"
            f" ({source.width}x{source.height}, widest aspect)"
        )
        try:
            target = detect.choose_target(desktop_sizes, source.size)
            size = desktop_sizes[target]
            lines.append(
                f"auto-detected target: display {target}"
                f" ({size[0]}x{size[1]}, closest to 16:9 among the others)"
            )
            lines.append("")
            lines.append("To pin these choices, save this as %APPDATA%\\uwmirror\\config.toml:")
            lines.append("")
            lines.append(f"  source = {source.index}")
            lines.append(f"  target = {target}")
        except detect.DetectionError as exc:
            lines.append(f"auto-detected target: FAILED — {exc}")
    except detect.DetectionError as exc:
        lines.append(f"auto-detected source: FAILED — {exc}")

    return "\n".join(lines)


def run(backend: str = "dxcam") -> int:
    """Gather real enumerations and print the report."""
    import pygame

    from uwmirror import winapi
    from uwmirror.capture import output_info_text

    outputs = detect.parse_output_info(output_info_text(backend))

    pygame.display.init()
    try:
        desktop_sizes = pygame.display.get_desktop_sizes()
    finally:
        pygame.display.quit()

    monitors = winapi.list_monitors()

    print(format_report(outputs, desktop_sizes, monitors))
    return 0
