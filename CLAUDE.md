# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**uwmirror** — Windows-only tool mirroring the center 16:9 region of an ultrawide monitor to a TV/secondary display: dxcam (DXGI Desktop Duplication) capture → numpy → pygame-ce presentation in a borderless window. Published to PyPI as `uwmirror` from GitHub `j-Allard-22/uwmirror` via tag-triggered trusted publishing. The original design rationale lives in [docs/dev-plan.md](docs/dev-plan.md).

## Commands

```powershell
py -3.12 -m venv .venv ; .venv\Scripts\activate
python -m pip install --upgrade pip     # pip >= 25.1 needed for --group
pip install -e . --group dev

ruff check . ; ruff format --check .    # lint (E,F,W,I,UP,B,SIM,RUF), line length 100
ruff check --fix . ; ruff format .      # autofix
mypy                                    # strict, src/ only (configured in pyproject)
pytest                                  # headless (SDL dummy driver), coverage gate 75%
pytest tests/test_geometry.py -k crop --no-cov   # single test, skip the coverage gate
pytest -m local_display --no-cov        # real-capture tests; dev machine only, never CI
uwmirror diagnose                       # live check of monitor enumerations

pip install -e . --group build-exe ; pyinstaller uwmirror.spec --noconfirm   # -> dist\uwmirror.exe
```

**Three different Python versions are in play, deliberately:** runtime floor is **3.10** (ruff `target-version = "py310"` enforces the syntax ceiling; `config.py` shims `tomllib`/`tomli` for it), mypy type-checks under **3.12** (numpy 2.x stubs use PEP 695 syntax mypy rejects on older targets), and CI runs the test matrix on **3.10 / 3.12 / 3.14**. Write 3.10-compatible code even though mypy would accept newer syntax. Every module uses `from __future__ import annotations`.

## Architecture

Strict pure/I-O split so logic tests run on headless CI (real Desktop Duplication does not work on hosted runners — CI mocks dxcam and runs pygame under `SDL_VIDEODRIVER=dummy`):

- **Pure (no Windows/pygame imports):** `geometry` (crop/coordinate math), `config` (Settings + TOML + precedence CLI > file > auto-detect), `detect` (parse `dxcam.output_info()` text, source/target heuristics, monitor matching), `recovery` (backoff policy), hotkey parsing in `hotkeys`, the `Command`/`AppState` reducer in `app`.
- **I/O:** `winapi` (ALL ctypes, private WinDLL instances with argtypes), `capture` (dxcam behind a `CaptureBackend` Protocol — the mock seam), `display` (pygame Presenter), `cursor` (overlay), `hotkeys.HotkeyListener` (RegisterHotKey message-loop thread), `tray` (optional pystray icon, its own thread), `diagnose`, `cli`.
- `app.run()` wires everything; `app.run_loop()` takes only injected callables (`LoopDeps`) and is tested with fakes from `tests/fakes.py`. Both `HotkeyListener` and `TrayController` push onto `queue.SimpleQueue`s that `run()`'s `get_commands` drains into `LoopCommand`s (`Command` for the payload-free toggles, the frozen `SetFps` dataclass for the tray's frame-rate presets); `run_loop` reports state changes back through the optional `LoopDeps.on_state` hook (the tray uses it for its checkmarks and its Frame rate radio).
- **The loop is driven by `AppState`, not by `LoopDeps`.** `LoopDeps.initial_fps` is only a seed — every tick reads `state.fps`, so a `SetFps` takes effect immediately. `reduce_state` folds with `dataclasses.replace` rather than rebuilding `AppState(...)` field by field, so a field added later can't be silently reset by a command that doesn't mention it (there's a regression test).
- **Detection heuristics** (`detect`): source = the output with the *widest aspect*, ties broken by primary then lowest index; target = among displays whose resolution differs from the source's, the one *closest to 16:9*. Both are overridable by `--source`/`--target`, and `diagnose` prints exactly what they'd pick.
- **Tray is an optional extra** (`uwmirror[tray]` → pystray + Pillow): `app._start_tray` degrades to `None` with a logged note if unavailable, so the global quit hotkey (`Ctrl+Alt+Q`, in core) is always the fallback. Frame rate is the one control with no hotkey fallback — without the extra, `--fps` is the only way to set it. In pystray, a submenu is an item whose *action* is a `Menu`; `radio=True` only renders as a radio when `checked` is also passed, and `checked` must be a callable taking the item. Build those predicates with a factory (`tray._is_fps`), never an inline lambda in the loop — a shared closure cell makes every checkmark move as a block. `tray.draw_icon_image` is the single icon source, reused by `packaging/make_icon.py` to generate the exe `.ico` — no committed binary asset. CI's mypy job installs no extras, so `tray.py` must type-check with pystray/Pillow absent (hence the `Any`-typed icon and the `ignore_missing_imports` override).
- **Nothing is presented without focus theft:** `display.Presenter` sets `SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN` *before* `set_mode`, and `winapi.set_topmost_noactivate` uses `SWP_NOACTIVATE`. That's precisely why the control surface has to be global hotkeys + tray.

## Critical constraints (violating these breaks the app)

- **DPI awareness before pygame window work**: `cli.main()` calls `winapi.set_dpi_awareness()` before importing anything pygame-facing. `cli.py`'s top-level imports (`config`, `capture`, `detect`, `hotkeys`) must stay pygame-free; `app`, `display`, `cursor`, `tray`, `diagnose`, and `winapi` are imported *inside* functions. Don't hoist those imports.
- **`video_mode=True` on `camera.start()`** — without it a static desktop stops delivering frames.
- **Crop via dxcam `region=`**, never post-capture numpy slicing (limits GPU→CPU readback).
- **dxcam `output_idx` and pygame `display` index are independent enumerations** — `detect` picks both; `diagnose` shows both; never assume they match.
- **dxcam >= 0.3 gotchas** (all handled in `capture.DxcamCapture`; don't undo):
  - Its default frame processor lazily imports **cv2** and crashes without opencv-python → we pass `processor_backend="numpy"` (with a `TypeError` fallback for dxcam-cpp).
  - It recovers from device loss *internally*: after a resolution change it silently resumes with a clamped, wrong-shape region, and during monitor sleep `get_latest_frame()` blocks forever. Hence the reader thread + `FRAME_TIMEOUT` + frame-shape validation, all converting failures to `CaptureLost` so `app.run_loop` recreates the backend with a recomputed crop.
  - Its factory **caches camera instances per output**, so `stop()` must call `release()` even when `stop()` itself raised — otherwise the next `create()` hands back the dead camera.
  - It bakes `target_fps` into `camera.start()` and exposes **no setter**, so a frame-rate change reuses the device-lost path (`backend.stop(); backend = None`, then recreate) rather than mutating the live backend. A `set_fps` on the Protocol would need a second teardown that skips `release()` — see the bullet above for why that's a trap.
- **Crop math:** `crop_w = height × 16/9` at full height, centered (generalized to the target display's aspect). 5120×1440 → 2560×1440; 3840×1080 → 1920×1080. Never 1920×1440 (4:3 — a corrected design error; there's a regression test). `Region` is dxcam-style `(left, top, right, bottom)` with exclusive right/bottom.
- **All ctypes stays in `winapi.py`**, with explicit argtypes/restype on private `WinDLL` instances (64-bit handle safety).
- **`Presenter.present()` blits but does not flip** — the loop draws the cursor overlay on top, then calls `flip()`. Keep that ordering.
- **No-console builds have `sys.stderr is None`** (the exe *and* the `uwmirrorw` gui-script). `cli._setup_logging` and `cli._report_error` detect that and write to `%APPDATA%\uwmirror\uwmirror.log`. Never assume a stream exists.

## Adding a setting

Five places, and the fourth is the one that silently swallows a flag if missed:

1. `config.Settings` — add the field + default (this auto-extends `_VALID_KEYS`, so the TOML loader accepts it).
2. `config._validate` — add the type/range check.
3. `cli._add_run_options` — add the argparse flag with **`default=None`** (`resolve()` reads `None` as "not supplied"; a real default here would silently outrank the config file). Booleans use `argparse.BooleanOptionalAction`.
4. `cli._settings_from_args` — add the name to the explicit tuple. Omit it and the flag parses fine and is then ignored.
5. The options table in [README.md](README.md).

## Testing conventions

- Tests import fakes from `tests/fakes.py` (protocol-level `FakeCapture`, `FakePresenter`, `FakeScreen`, `ScriptedCommands`).
- `tests/test_capture.py` has its own `FakeDxCamera` mimicking the dxcam module surface; keep it pacing (`time.sleep`) so `DxcamCapture`'s reader thread doesn't spin.
- Anything needing a real desktop/GPU goes under `tests/integration/` with `@pytest.mark.local_display` (excluded by default via pyproject `addopts`, which is also why running them needs `--no-cov`).
- `tests/conftest.py` forces `SDL_VIDEODRIVER=dummy` at import time — before any pygame import anywhere in the run. Don't import pygame above it.
- `tests/test_winapi.py` calls the real user32 — read-only smoke tests that pass on windows-latest, `skipif`'d off Windows. dxcam is the only thing that must always be faked.
- The manual pre-release checklist is in [docs/dev-plan.md](docs/dev-plan.md) §8 (resolution change, monitor sleep, fullscreen game, autostart, resource budget).

## Packaging the exe

`uwmirror.spec` builds a single-file, no-console `uwmirror.exe` (PyInstaller) from `packaging/pyinstaller_entry.py` — a separate script because PyInstaller needs an entry that *runs*, not a module that only defines `main`. The load-bearing detail: `collect_all("dxcam")` + the `dxcam.processor._numpy_kernels` hidden import — dxcam loads that compiled kernel via `importlib.import_module()` (invisible to PyInstaller), and without it dxcam silently falls back to a cv2 path we don't ship (and explicitly `excludes`) and the exe crashes on the first frame. `console=False` means stdio is `None`, so `cli.py` logs to `%APPDATA%\uwmirror\uwmirror.log`. Full rationale in [docs/build-exe.md](docs/build-exe.md). Build on Windows with Python 3.12; UPX is off (AV false positives).

## Release

Bump `__version__` in `src/uwmirror/__init__.py` (hatch reads it as the single version source), move CHANGELOG `[Unreleased]` into a dated section, tag `vX.Y.Z`, push the tag. `.github/workflows/release.yml` builds the wheel/sdist and (on windows-latest) `uwmirror.exe`, publishes to PyPI (OIDC trusted publishing — the publisher must be registered on PyPI for `uwmirror`), and creates the GitHub Release with the CHANGELOG section as notes plus the exe attached. The notes extractor regex-matches `## [X.Y.Z]`, so the heading must match the tag minus its `v`. Full runbook (incl. one-time PyPI trusted-publisher registration): [docs/releasing.md](docs/releasing.md).

## Known limitations (by design, don't "fix")

Desktop Duplication omits the cursor (we overlay an arrow — always an arrow), shows black for DRM content, and washes out HDR desktops. The pause/blank hotkeys are global because the mirror window intentionally never takes focus.
