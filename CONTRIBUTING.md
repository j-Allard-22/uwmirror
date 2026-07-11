# Contributing to uwmirror

Thanks for considering a contribution! This is a small, focused tool; the bar
for changes is "keeps it light and Windows-native".

## Dev setup

```
git clone https://github.com/j-Allard-22/uwmirror
cd uwmirror
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e . --group dev
```

## Quality gates (same as CI)

```
ruff check . && ruff format --check .   # lint + formatting
mypy                                    # strict type checking on src/
pytest                                  # unit tests, headless, with coverage gate
```

Run `ruff check --fix . && ruff format .` to auto-fix most lint issues.

## Architecture in one paragraph

Pure logic (`geometry`, `config`, `detect`, `recovery`, hotkey parsing, the
`app` state reducer) is strictly separated from I/O (`winapi` for ctypes,
`capture` for dxcam, `display` for pygame). The app loop only sees a
`CaptureBackend` protocol, so tests inject fakes and CI never touches real
Desktop Duplication (which doesn't work on hosted runners). Keep new logic on
the pure side of that line whenever possible, and keep *all* ctypes in
`winapi.py`.

## Testing

- Unit tests run headless (`SDL_VIDEODRIVER=dummy` is set in `tests/conftest.py`)
  and must pass on GitHub's windows-latest runners.
- Anything requiring real capture or a visible window goes in
  `tests/integration/` with the `local_display` marker, and runs manually:
  `pytest -m local_display --no-cov`.
- Before a release, walk the manual checklist: static desktop for 60 s,
  resolution change, monitor sleep/wake, fullscreen game entry/exit,
  autostart after reboot, and a 10-minute CPU/RAM sanity check.

## Pull requests

- Keep the dependency footprint where it is (dxcam, pygame-ce, numpy);
  new runtime dependencies need a strong case.
- Add or update tests for behavior changes.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Conventional-commit-style messages (`fix:`, `feat:`, `docs:`) are
  appreciated but not enforced.
