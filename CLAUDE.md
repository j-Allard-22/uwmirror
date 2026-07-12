# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**uwmirror** — Windows-only tool mirroring the center 16:9 region of an ultrawide monitor to a TV/secondary display: dxcam (DXGI Desktop Duplication) capture → numpy → pygame-ce presentation in a borderless window. Published to PyPI as `uwmirror` from GitHub `j-Allard-22/uwmirror` via tag-triggered trusted publishing. The original design rationale lives in [docs/dev-plan.md](docs/dev-plan.md).

## Commands

```powershell
py -3.12 -m venv .venv ; .venv\Scripts\activate
python -m pip install --upgrade pip     # pip >= 25.1 needed for --group
pip install -e . --group dev

ruff check . ; ruff format --check .    # lint (E,F,W,I,UP,B,SIM,RUF)
mypy                                    # strict, src/ only (configured in pyproject)
pytest                                  # headless (SDL dummy driver), coverage gate 75%
pytest tests/test_geometry.py -k crop --no-cov   # single test, skip the coverage gate
pytest -m local_display --no-cov        # real-capture tests; dev machine only, never CI
uwmirror diagnose                       # live check of monitor enumerations

pip install -e . --group build-exe ; pyinstaller uwmirror.spec --noconfirm   # -> dist\uwmirror.exe
```

## Architecture

Strict pure/I-O split so logic tests run on headless CI (real Desktop Duplication does not work on hosted runners — CI mocks dxcam and runs pygame under `SDL_VIDEODRIVER=dummy`):

- **Pure (no Windows/pygame imports):** `geometry` (crop/coordinate math), `config` (Settings + TOML + precedence CLI > file > auto-detect), `detect` (parse `dxcam.output_info()` text, source/target heuristics, monitor matching), `recovery` (backoff policy), hotkey parsing in `hotkeys`, the `Command`/`AppState` reducer in `app`.
- **I/O:** `winapi` (ALL ctypes, private WinDLL instances with argtypes), `capture` (dxcam behind a `CaptureBackend` Protocol — the mock seam), `display` (pygame Presenter), `cursor` (overlay), `hotkeys.HotkeyListener` (RegisterHotKey message-loop thread), `tray` (optional pystray icon, its own thread), `diagnose`, `cli`.
- `app.run()` wires everything; `app.run_loop()` takes only injected callables (`LoopDeps`) and is tested with fakes from `tests/fakes.py`. Both `HotkeyListener` and `TrayController` push onto `queue.SimpleQueue`s that `run()`'s `get_commands` drains into `Command`s; `run_loop` reports state changes back through the optional `LoopDeps.on_state` hook (the tray uses it for its checkmarks).
- **Tray is an optional extra** (`uwmirror[tray]` → pystray + Pillow): `app._start_tray` degrades to `None` with a logged note if unavailable, so the global quit hotkey (`Ctrl+Alt+Q`, in core) is always the fallback. `tray.draw_icon_image` is the single icon source, reused by `packaging/make_icon.py` to generate the exe `.ico` — no committed binary asset.

## Critical constraints (violating these breaks the app)

- **DPI awareness before pygame window work**: `cli.main()` calls `winapi.set_dpi_awareness()` before importing/initializing anything pygame-facing. Keep pygame imports out of module top-levels in `cli.py`.
- **`video_mode=True` on `camera.start()`** — without it a static desktop stops delivering frames.
- **Crop via dxcam `region=`**, never post-capture numpy slicing (limits GPU→CPU readback).
- **dxcam `output_idx` and pygame `display` index are independent enumerations** — `detect` picks both; `diagnose` shows both; never assume they match.
- **dxcam >= 0.3 gotchas** (all handled in `capture.DxcamCapture`; don't undo):
  - Its default frame processor lazily imports **cv2** and crashes without opencv-python → we pass `processor_backend="numpy"` (with a `TypeError` fallback for dxcam-cpp).
  - It recovers from device loss *internally*: after a resolution change it silently resumes with a clamped, wrong-shape region, and during monitor sleep `get_latest_frame()` blocks forever. Hence the reader thread + `FRAME_TIMEOUT` + frame-shape validation, all converting failures to `CaptureLost` so `app.run_loop` recreates the backend with a recomputed crop.
- **Crop math:** `crop_w = height × 16/9` at full height, centered (generalized to the target display's aspect). 5120×1440 → 2560×1440; 3840×1080 → 1920×1080. Never 1920×1440 (4:3 — a corrected design error; there's a regression test).
- **All ctypes stays in `winapi.py`**, with explicit argtypes/restype on private `WinDLL` instances (64-bit handle safety).

## Testing conventions

- Tests import fakes from `tests/fakes.py` (protocol-level `FakeCapture`, `FakePresenter`, `ScriptedCommands`).
- `tests/test_capture.py` has its own `FakeDxCamera` mimicking the dxcam module surface; keep it pacing (`time.sleep`) so `DxcamCapture`'s reader thread doesn't spin.
- Anything needing a real desktop/GPU goes under `tests/integration/` with `@pytest.mark.local_display` (excluded by default via pyproject `addopts`).
- The manual pre-release checklist is in [docs/dev-plan.md](docs/dev-plan.md) §8 (resolution change, monitor sleep, fullscreen game, autostart, resource budget).

## Packaging the exe

`uwmirror.spec` builds a single-file, no-console `uwmirror.exe` (PyInstaller). The load-bearing detail: `collect_all("dxcam")` + `--hidden-import dxcam.processor._numpy_kernels` — dxcam loads that compiled kernel via `importlib.import_module()` (invisible to PyInstaller), and without it dxcam silently falls back to a cv2 path we don't ship and the exe crashes on the first frame. `console=False` means stdio is `None`, so `cli.py` logs to `%APPDATA%\uwmirror\uwmirror.log`. Full rationale in [docs/build-exe.md](docs/build-exe.md). Build on Windows with Python 3.12; UPX is off (AV false positives).

## Release

Bump `__version__` in `src/uwmirror/__init__.py`, move CHANGELOG `[Unreleased]` into a dated section, tag `vX.Y.Z`, push the tag. `.github/workflows/release.yml` builds the wheel/sdist and (on windows-latest) `uwmirror.exe`, publishes to PyPI (OIDC trusted publishing — the publisher must be registered on PyPI for `uwmirror`), and creates the GitHub Release with the CHANGELOG section as notes plus the exe attached.

## Known limitations (by design, don't "fix")

Desktop Duplication omits the cursor (we overlay an arrow — always an arrow), shows black for DRM content, and washes out HDR desktops. The pause/blank hotkeys are global because the mirror window intentionally never takes focus.
