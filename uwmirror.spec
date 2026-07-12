# PyInstaller spec — single-file, no-console uwmirror.exe.
# Build:  pyinstaller uwmirror.spec   (on Windows, with the build-exe deps installed)
#
# Collection notes (see docs/build-exe.md for the full rationale):
#   * dxcam loads its compiled numpy kernel via importlib.import_module(), which
#     PyInstaller's static analysis cannot see. Without it, dxcam silently falls
#     back to an OpenCV code path we deliberately don't ship -> crash on the first
#     frame. collect_all("dxcam") copies the .pyd regardless of import tracing.
#   * pystray picks its backend (pystray._win32) dynamically.
#   * comtypes (dxcam's COM layer) is over-collected as cheap insurance.
#   * pygame-ce ships its own PyInstaller hook, so it needs nothing here.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, str(Path(SPECPATH) / "packaging"))  # noqa: F821 - SPECPATH is injected
from make_icon import build_ico

icon_path = build_ico(Path(SPECPATH) / "build" / "uwmirror.ico")  # noqa: F821

datas = []
binaries = []
hiddenimports = [
    "pystray._win32",
    "comtypes.stream",
    "dxcam.processor._numpy_kernels",
]
for _pkg in ("dxcam", "comtypes"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    [str(Path(SPECPATH) / "packaging" / "pyinstaller_entry.py")],  # noqa: F821
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["cv2", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="uwmirror",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressed onefile exes trip antivirus heuristics
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no console window; stdio is None -> cli.py logs to a file
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)
