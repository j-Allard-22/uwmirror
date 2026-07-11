"""Settings model, TOML loading, and precedence resolution.

Precedence: CLI flag > config file > built-in default. Auto-detection fills
``source``/``target`` at runtime only when both CLI and file leave them unset.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

SCALE_MODES = ("smooth", "fast")
BACKENDS = ("dxcam", "dxcam-cpp")
LOG_LEVELS = ("debug", "info", "warning", "error")
MAX_FPS = 240


class ConfigError(Exception):
    """Invalid configuration value or file."""


@dataclass(frozen=True)
class Settings:
    """Fully resolved runtime settings."""

    source: int | None = None
    target: int | None = None
    fps: int = 60
    scale: str = "smooth"
    cursor: bool = True
    topmost: bool = True
    windowed: bool = False
    hotkeys: bool = True
    backend: str = "dxcam"
    log_level: str = "info"
    pause_hotkey: str = "ctrl+alt+p"
    blank_hotkey: str = "ctrl+alt+b"


_VALID_KEYS = {f.name for f in fields(Settings)}


def default_config_path() -> Path:
    """``%APPDATA%\\uwmirror\\config.toml`` (falls back to the home directory)."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home()
    return base / "uwmirror" / "config.toml"


def load_toml(path: Path) -> dict[str, Any]:
    """Read a config file into a plain dict, normalizing kebab-case keys."""
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc

    normalized = {key.replace("-", "_"): value for key, value in raw.items()}
    unknown = sorted(set(normalized) - _VALID_KEYS)
    if unknown:
        raise ConfigError(
            f"{path}: unknown option(s) {', '.join(unknown)}; "
            f"valid options are {', '.join(sorted(_VALID_KEYS))}"
        )
    return normalized


def resolve(cli: dict[str, Any], file_cfg: dict[str, Any]) -> Settings:
    """Merge CLI values over file values over defaults, then validate.

    ``cli`` uses ``None`` for flags the user did not pass.
    """
    merged: dict[str, Any] = {}
    for name in _VALID_KEYS:
        if cli.get(name) is not None:
            merged[name] = cli[name]
        elif file_cfg.get(name) is not None:
            merged[name] = file_cfg[name]

    settings = Settings(**merged)
    _validate(settings)
    return settings


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate(settings: Settings) -> None:
    if not _is_int(settings.fps) or not 1 <= settings.fps <= MAX_FPS:
        raise ConfigError(f"fps must be an integer between 1 and {MAX_FPS}, got {settings.fps!r}")
    if settings.scale not in SCALE_MODES:
        raise ConfigError(f"scale must be one of {SCALE_MODES}, got {settings.scale!r}")
    if settings.backend not in BACKENDS:
        raise ConfigError(f"backend must be one of {BACKENDS}, got {settings.backend!r}")
    if settings.log_level not in LOG_LEVELS:
        raise ConfigError(f"log_level must be one of {LOG_LEVELS}, got {settings.log_level!r}")
    for name in ("source", "target"):
        value = getattr(settings, name)
        if value is not None and (not _is_int(value) or value < 0):
            raise ConfigError(f"{name} must be a non-negative integer, got {value!r}")
    for name in ("cursor", "topmost", "windowed", "hotkeys"):
        if not isinstance(getattr(settings, name), bool):
            raise ConfigError(f"{name} must be true or false, got {getattr(settings, name)!r}")
    for name in ("pause_hotkey", "blank_hotkey"):
        if not isinstance(getattr(settings, name), str):
            raise ConfigError(f"{name} must be a string, got {getattr(settings, name)!r}")
