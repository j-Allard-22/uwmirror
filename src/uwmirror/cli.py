"""Command-line interface: ``uwmirror [run|diagnose]``.

Windows-only modules (winapi, app, diagnose — anything touching pygame or
ctypes.windll) are imported lazily, after the platform gate. DPI awareness
is set before any pygame window work (a hard requirement on mixed-DPI
setups).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from uwmirror import __version__, config
from uwmirror.capture import CaptureLost
from uwmirror.detect import DetectionError
from uwmirror.hotkeys import HotkeyError

_COMMANDS = {"run", "diagnose"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uwmirror",
        description="Mirror the center 16:9 of an ultrawide monitor to a TV.",
        epilog=(
            "Running with no arguments starts the mirror with auto-detected"
            " displays; run 'uwmirror diagnose' first to check the detection."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="start mirroring (the default when no command is given)"
    )
    _add_run_options(run_parser)

    diagnose_parser = subparsers.add_parser(
        "diagnose", help="list capture outputs and displays, and explain auto-detection"
    )
    diagnose_parser.add_argument(
        "--backend", choices=config.BACKENDS, default="dxcam", help="capture library to query"
    )
    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        type=int,
        default=None,
        metavar="N",
        help="dxcam output index to capture (default: auto-detect the widest display)",
    )
    parser.add_argument(
        "--target",
        type=int,
        default=None,
        metavar="N",
        help="pygame display index to present on (default: auto-detect;"
        " NOTE: numbered independently from --source)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=None,
        help="capture/present rate (default 15; also switchable at runtime from the tray)",
    )
    parser.add_argument(
        "--scale",
        choices=config.SCALE_MODES,
        default=None,
        help="downscale filter: smooth (bilinear) or fast (nearest); default smooth",
    )
    parser.add_argument(
        "--cursor",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="overlay the mouse cursor (Desktop Duplication omits it); default on",
    )
    parser.add_argument(
        "--topmost",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="keep the mirror window above other windows; default on",
    )
    parser.add_argument(
        "--windowed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="run in a small framed window for debugging; default off",
    )
    parser.add_argument(
        "--hotkeys",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="register global pause/blank/quit hotkeys; default on",
    )
    parser.add_argument(
        "--tray",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show a system-tray icon for pause/blank/quit; default on (needs the [tray] extra)",
    )
    parser.add_argument(
        "--pause-hotkey",
        default=None,
        metavar="SPEC",
        help="global hotkey to freeze the mirror (default ctrl+alt+p)",
    )
    parser.add_argument(
        "--blank-hotkey",
        default=None,
        metavar="SPEC",
        help="global hotkey to black out the mirror (default ctrl+alt+b)",
    )
    parser.add_argument(
        "--quit-hotkey",
        default=None,
        metavar="SPEC",
        help="global hotkey to quit the mirror (default ctrl+alt+q)",
    )
    parser.add_argument(
        "--backend",
        choices=config.BACKENDS,
        default=None,
        help="capture library (dxcam-cpp requires: pip install uwmirror[cpp])",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="TOML config file (default: %%APPDATA%%\\uwmirror\\config.toml)",
    )
    parser.add_argument("--log-level", choices=config.LOG_LEVELS, default=None, help="default info")


def _normalize_argv(argv: list[str]) -> list[str]:
    """Make ``run`` the default subcommand: ``uwmirror --fps 30`` == ``uwmirror run --fps 30``."""
    if not argv:
        return ["run"]
    if argv[0] in _COMMANDS or argv[0] in {"-h", "--help", "--version"}:
        return argv
    return ["run", *argv]


def _settings_from_args(args: argparse.Namespace) -> config.Settings:
    cli_values: dict[str, Any] = {
        name: getattr(args, name, None)
        for name in (
            "source",
            "target",
            "fps",
            "scale",
            "cursor",
            "topmost",
            "windowed",
            "hotkeys",
            "tray",
            "backend",
            "log_level",
            "pause_hotkey",
            "blank_hotkey",
            "quit_hotkey",
        )
    }
    path = args.config if args.config is not None else config.default_config_path()
    file_cfg: dict[str, Any] = {}
    if path.is_file():
        file_cfg = config.load_toml(path)
    elif args.config is not None:
        raise config.ConfigError(f"config file not found: {path}")
    return config.resolve(cli_values, file_cfg)


def _fallback_log_path() -> Path:
    return config.default_config_path().parent / "uwmirror.log"


def _report_error(message: str) -> None:
    """Surface a fatal error even under pythonw, where stderr doesn't exist."""
    if sys.stderr is not None:
        print(f"uwmirror: {message}", file=sys.stderr)
        return
    try:
        log_path = _fallback_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"uwmirror: {message}\n")
    except OSError:  # nowhere left to report to
        pass


def _setup_logging(level: str) -> None:
    handler: logging.Handler
    if sys.stderr is None:  # pythonw (uwmirrorw): no console — log to a file instead
        log_path = _fallback_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level.upper())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_normalize_argv(sys.argv[1:] if argv is None else argv))

    if sys.platform != "win32":
        print(
            "uwmirror only runs on Windows: it captures via DXGI Desktop Duplication.",
            file=sys.stderr,
        )
        return 2

    try:
        if args.command == "diagnose":
            _setup_logging("info")
            from uwmirror import diagnose, winapi

            winapi.set_dpi_awareness()
            return diagnose.run(backend=args.backend)

        settings = _settings_from_args(args)
        _setup_logging(settings.log_level)
        from uwmirror import app, winapi

        winapi.set_dpi_awareness()
        return app.run(settings)
    except (config.ConfigError, DetectionError, HotkeyError, CaptureLost) as exc:
        _report_error(str(exc))
        return 2
    except KeyboardInterrupt:
        return 130
