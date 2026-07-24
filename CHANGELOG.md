# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-07-24

### Added

- Tray **Frame rate** submenu (15 / 30 / 60 / 120 fps) with a live radio
  checkmark, changing the capture and present rate at runtime. Switching
  restarts the capture, so the mirror freezes briefly. The choice applies to
  the running session only and is never written back to `config.toml`.

### Changed

- **The default frame rate is now 15 fps (was 60).** Mirroring a mostly static
  desktop does not need 60, and the new tray submenu makes raising it a
  two-click action. Configurations that already set `fps` are unaffected; pass
  `--fps 60` or set `fps = 60` in `config.toml` to restore the old default.

## [1.0.0] - 2026-07-11

### Added

- Center-crop mirroring of an ultrawide display to a secondary display via
  DXGI Desktop Duplication (dxcam) and pygame-ce, with automatic source/target
  detection and `--source`/`--target` overrides.
- `uwmirror diagnose` — side-by-side listing of dxcam outputs, pygame
  displays, and Windows monitor rects, with a ready-to-paste config snippet.
- Cursor overlay (Desktop Duplication omits the hardware cursor).
- Global pause (`Ctrl+Alt+P`), blank (`Ctrl+Alt+B`), and quit (`Ctrl+Alt+Q`)
  hotkeys via `RegisterHotKey`; local window keys as fallback.
- Optional system-tray icon (`uwmirror[tray]`) with Pause/Blank/Quit and live
  state — the primary control surface for the focus-less mirror window.
- Standalone single-file `uwmirror.exe` (PyInstaller, no console, tray bundled)
  attached to each GitHub Release for users without Python.
- Topmost, no-focus-steal mirror window.
- TOML configuration at `%APPDATA%\uwmirror\config.toml` with
  CLI > file > auto-detection precedence.
- Automatic capture recovery (resolution changes, monitor sleep,
  exclusive-fullscreen games) with capped exponential backoff.
- `uwmirrorw` console-less entry point for Task Scheduler autostart.

[Unreleased]: https://github.com/j-Allard-22/uwmirror/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/j-Allard-22/uwmirror/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/j-Allard-22/uwmirror/releases/tag/v1.0.0
