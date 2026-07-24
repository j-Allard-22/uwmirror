# uwmirror

[![CI](https://github.com/j-Allard-22/uwmirror/actions/workflows/ci.yml/badge.svg)](https://github.com/j-Allard-22/uwmirror/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/uwmirror)](https://pypi.org/project/uwmirror/)
[![Python](https://img.shields.io/pypi/pyversions/uwmirror)](https://pypi.org/project/uwmirror/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Mirror the center 16:9 of an ultrawide monitor to a TV — without running OBS.

You have a 32:9 ultrawide (5120×1440 or 3840×1080) and a TV on the same PC in
Extend mode. You want the middle of the ultrawide — where the game or content
actually is — fullscreen on the TV, with nothing else running. That's the whole
tool: a borderless window on the TV showing a live center crop of the ultrawide,
captured with the same zero-copy DXGI Desktop Duplication API OBS uses, in a
single lightweight Python process (~150 MB RAM, a few percent of one core).

<!-- demo: docs/demo.gif -->
*(demo GIF coming soon)*

**Windows only.** Desktop Duplication is a Windows API; this tool is Windows 10/11 by design.

## Install

**No Python?** Download `uwmirror.exe` from the [latest release](https://github.com/j-Allard-22/uwmirror/releases) —
a single self-contained file with the system-tray icon built in. Double-click
it (no console window), or point Task Scheduler at it for
[autostart](docs/autostart.md).

**With Python (3.10+):**

```
pipx install "uwmirror[tray]"      # or: uvx "uwmirror[tray]", or: pip install "uwmirror[tray]"
```

The `[tray]` extra adds the system-tray icon (pystray + Pillow). Plain
`uwmirror` works too — you just control it with the global hotkeys instead of a
tray. All dependencies are pure wheels (dxcam, pygame-ce, numpy).

## Quickstart

```
uwmirror diagnose   # see both display enumerations and what auto-detection picks
uwmirror            # start mirroring
```

With two displays in Extend mode that's usually all you need: the widest
display becomes the capture source and the other display the mirror target.
If detection guesses wrong, pin the indices:

```
uwmirror --source 0 --target 1
```

> **Note:** `--source` is a **dxcam output index** and `--target` is a
> **pygame display index** — two independent numbering schemes that don't
> necessarily match. `uwmirror diagnose` shows both.

Press **Esc** or **Q** in the mirror window to quit (or `Ctrl+C` in the console).

## Options

Every flag can also be set in `%APPDATA%\uwmirror\config.toml` (same names,
`_` or `-` both accepted). Precedence: CLI flag > config file > auto-detection.

| Flag | Default | Description |
|---|---|---|
| `--source N` | auto | dxcam output index of the monitor to capture |
| `--target N` | auto | pygame display index of the TV |
| `--fps N` | 15 | capture/present rate; also switchable at runtime from the tray |
| `--scale smooth\|fast` | smooth | downscale filter when the crop is larger than the TV |
| `--cursor` / `--no-cursor` | on | overlay the mouse cursor (capture omits it) |
| `--topmost` / `--no-topmost` | on | keep the mirror above other windows, without stealing focus |
| `--windowed` | off | small framed window instead of fullscreen (debugging) |
| `--hotkeys` / `--no-hotkeys` | on | global pause/blank/quit hotkeys |
| `--tray` / `--no-tray` | on | system-tray icon (needs the `[tray]` extra) |
| `--pause-hotkey SPEC` | `ctrl+alt+p` | freeze the mirror on the last frame |
| `--blank-hotkey SPEC` | `ctrl+alt+b` | black out the TV (privacy) |
| `--quit-hotkey SPEC` | `ctrl+alt+q` | quit the mirror |
| `--backend dxcam\|dxcam-cpp` | dxcam | capture library (`pip install uwmirror[cpp]` for the C++ fork) |
| `--config PATH` | `%APPDATA%\uwmirror\config.toml` | config file location |
| `--log-level LEVEL` | info | debug, info, warning, error |

Example `config.toml` (run `uwmirror diagnose` to get one pre-filled):

```toml
source = 0
target = 1
fps = 30
pause-hotkey = "ctrl+alt+f9"
```

## Controls

The mirror window on the TV deliberately never takes focus, so you drive it
from the **tray icon** (right-click → Pause / Blank / Frame rate / Quit, with
live checkmarks) and from **global hotkeys**:

| Keys | Action |
|---|---|
| `Ctrl+Alt+P` (global) | pause/resume — freezes the last frame |
| `Ctrl+Alt+B` (global) | blank/unblank — black screen |
| `Ctrl+Alt+Q` (global) | quit |
| `Space` / `B` / `Esc` / `Q` (mirror window focused) | same, as a local fallback |

Global hotkeys use `RegisterHotKey` — no admin rights, no keyboard hooks. If a
chord is taken by another app, uwmirror logs a warning and keeps running; pick
a different chord with `--pause-hotkey`/`--blank-hotkey`/`--quit-hotkey`.

**Frame rate** offers 15 / 30 / 60 / 120 fps. The default is 15 — a desktop
mirror rarely needs more, and raising it for a game or a video is two clicks.
Switching restarts the capture, so the mirror freezes for a moment. The choice
lasts for the session only and is never written back to `config.toml`; set
`fps` there (or pass `--fps`) to change the rate uwmirror *starts* at. A
non-preset value such as `--fps 90` simply leaves all four entries unchecked
until you pick one. Frame rate is tray-only — with no tray there is no runtime
control, so use `--fps`.

## Start automatically at logon

Point Task Scheduler at `uwmirror.exe`, or at `uwmirrorw` (the console-less
entry point of a `pip` install) — see [docs/autostart.md](docs/autostart.md)
for the one-line `schtasks` command and the reason for the startup delay.

## Limitations

Inherent to Desktop Duplication (OBS has the same ones):

- **No real cursor in the capture** — uwmirror draws its own arrow overlay;
  it's always an arrow (no I-beam/hand shapes).
- **DRM-protected content** (Netflix and friends) shows as a black region.
- **HDR desktops** look washed out on an SDR TV — run the desktop in SDR.
- **UAC prompts** briefly freeze the mirror (secure desktop); it recovers by itself.
- **Exclusive-fullscreen games** reset the capture device on entry/exit;
  uwmirror reinitializes within a couple of seconds. Borderless-windowed
  games avoid the hiccup entirely.

## Why not just OBS?

An OBS fullscreen projector does the same job well. uwmirror is for when you
don't want an OBS instance running for it: one process, no compositor, no UI,
roughly a third of the RAM (~150 MB vs ~400 MB), and it starts from Task
Scheduler in about a second. If you already run OBS for streaming, keep using
OBS.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version:

```
py -3.12 -m venv .venv && .venv\Scripts\activate
pip install -e . --group dev
ruff check . && ruff format --check . && mypy && pytest
```

Real-capture integration tests (need a real desktop + GPU): `pytest -m local_display --no-cov`.

Building the standalone exe is documented in [docs/build-exe.md](docs/build-exe.md).

## License

[MIT](LICENSE) © Jonathan Allard
