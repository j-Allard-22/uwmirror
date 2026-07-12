# Building the standalone `uwmirror.exe`

The release workflow builds a single-file, no-console `uwmirror.exe` with
[PyInstaller](https://pyinstaller.org) and attaches it to each GitHub Release,
so end users don't need Python installed. This page documents building it
locally and the collection choices baked into [`uwmirror.spec`](../uwmirror.spec).

## Build it

```powershell
py -3.12 -m venv .venv ; .venv\Scripts\activate
pip install -e . --group build-exe          # pyinstaller + pystray + pillow
pyinstaller uwmirror.spec --noconfirm        # -> dist\uwmirror.exe
```

Build **on Windows with Python 3.12** — PyInstaller bundles the interpreter it
runs under and can't cross-compile, and 3.12 is the project's dev/CI baseline.
The build regenerates `build\uwmirror.ico` from the tray glyph
([packaging/make_icon.py](../packaging/make_icon.py)), so there is no icon
committed as a binary asset.

The result is a ~35 MB self-contained exe. Double-click it (or point Task
Scheduler at it — see [autostart.md](autostart.md)) and it runs with no
console window, controlled from the tray icon and global hotkeys.

## Why the spec collects what it does

`--windowed` alone is not enough for this dependency stack:

- **`dxcam.processor._numpy_kernels`** — dxcam loads its compiled numpy kernel
  via `importlib.import_module()`, which PyInstaller's static analysis can't
  see. If the `.pyd` isn't bundled, dxcam silently falls back to an OpenCV code
  path uwmirror deliberately doesn't ship, and the exe **crashes on the first
  captured frame** with `ModuleNotFoundError: No module named 'cv2'`.
  `collect_all("dxcam")` plus an explicit hidden-import force it in.
- **`pystray._win32`** — pystray selects its OS backend dynamically; the
  Windows one must be named as a hidden import.
- **`comtypes`** — dxcam's COM layer; over-collected as cheap insurance
  (`comtypes.stream` is a known frozen-app gotcha).
- **pygame-ce** ships its own PyInstaller hook, so it needs nothing here.
- **UPX is disabled** (`upx=False`): UPX-compressed single-file exes are a
  classic antivirus/SmartScreen false-positive trigger.

## No console → logging goes to a file

With `console=False`, `sys.stdout`/`sys.stderr` are `None`. `uwmirror.cli`
detects this and routes all logging — and any fatal startup error — to
`%APPDATA%\uwmirror\uwmirror.log`. Check that file first when diagnosing the
frozen build.

## Verifying a build

Real DXGI capture needs a real desktop, so a fresh build is worth a manual
smoke test on a dev machine: run `dist\uwmirror.exe`, confirm no console
window appears, the tray icon shows up, and the log records
`capturing WxH region ... fps` with **no** `cv2` error.

## Antivirus / SmartScreen

An unsigned PyInstaller exe may draw a SmartScreen "unknown publisher" prompt
or an occasional AV false positive — inherent to unsigned bundled-interpreter
executables, not specific to uwmirror. The most effective fix is Authenticode
code-signing the released exe; UPX is already disabled to reduce the risk.
Users who prefer to avoid it entirely can `pip install uwmirror[tray]` instead.
