"""Generate the Windows ``.ico`` for the executable from the tray glyph.

Keeps the icon out of version control as a binary asset: it is drawn from the
same :func:`uwmirror.tray.draw_icon_image` used for the live tray icon, so the
app icon and tray icon can never drift apart. Run directly or import
:func:`build_ico` (the PyInstaller spec calls it at build time).
"""

from __future__ import annotations

from pathlib import Path

# Sizes Windows expects inside a multi-resolution .ico (taskbar, alt-tab, etc.).
_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def build_ico(dest: Path) -> Path:
    """Render the app icon at 256px and save a multi-size ``.ico`` to ``dest``."""
    from uwmirror.tray import draw_icon_image

    dest.parent.mkdir(parents=True, exist_ok=True)
    image = draw_icon_image(256)
    image.save(dest, format="ICO", sizes=_ICO_SIZES)
    return dest


if __name__ == "__main__":
    out = build_ico(Path(__file__).resolve().parent.parent / "build" / "uwmirror.ico")
    print(f"wrote {out}")
