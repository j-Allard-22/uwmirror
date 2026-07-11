# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-07-11

### Added

- Center-crop mirroring of an ultrawide display to a secondary display via
  DXGI Desktop Duplication (dxcam) and pygame-ce, with automatic source/target
  detection and `--source`/`--target` overrides.
- `uwmirror diagnose` — side-by-side listing of dxcam outputs, pygame
  displays, and Windows monitor rects, with a ready-to-paste config snippet.
- Cursor overlay (Desktop Duplication omits the hardware cursor).
- Global pause (`Ctrl+Alt+P`) and blank (`Ctrl+Alt+B`) hotkeys via
  `RegisterHotKey`; local window keys as fallback.
- Topmost, no-focus-steal mirror window.
- TOML configuration at `%APPDATA%\uwmirror\config.toml` with
  CLI > file > auto-detection precedence.
- Automatic capture recovery (resolution changes, monitor sleep,
  exclusive-fullscreen games) with capped exponential backoff.
- `uwmirrorw` console-less entry point for Task Scheduler autostart.

[Unreleased]: https://github.com/j-Allard-22/uwmirror/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/j-Allard-22/uwmirror/releases/tag/v1.0.0
