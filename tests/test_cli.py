import sys
from pathlib import Path

import pytest

from uwmirror import __version__
from uwmirror.cli import _normalize_argv, build_parser, main
from uwmirror.config import Settings


class TestNormalizeArgv:
    def test_empty_becomes_run(self):
        assert _normalize_argv([]) == ["run"]

    def test_flags_get_run_prepended(self):
        assert _normalize_argv(["--fps", "30"]) == ["run", "--fps", "30"]

    def test_explicit_commands_pass_through(self):
        assert _normalize_argv(["run", "--fps", "30"]) == ["run", "--fps", "30"]
        assert _normalize_argv(["diagnose"]) == ["diagnose"]

    def test_help_and_version_pass_through(self):
        assert _normalize_argv(["--help"]) == ["--help"]
        assert _normalize_argv(["--version"]) == ["--version"]


class TestVersionAndHelp:
    def test_version_prints_and_exits_zero(self, capsys: pytest.CaptureFixture):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_help_mentions_both_commands(self, capsys: pytest.CaptureFixture):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        out = capsys.readouterr().out
        assert "run" in out
        assert "diagnose" in out


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch):
    """Stub app.run and capture the Settings it receives."""
    import uwmirror.app as app_module

    received: list[Settings] = []

    def fake_run(settings: Settings) -> int:
        received.append(settings)
        return 0

    monkeypatch.setattr(app_module, "run", fake_run)
    return received


@pytest.mark.skipif(sys.platform != "win32", reason="main() gates on win32")
class TestMainDispatch:
    def test_defaults_flow_to_app_run(self, captured_run, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))  # avoid the dev machine's real config
        assert main([]) == 0
        assert captured_run == [Settings()]

    def test_flags_override_defaults(self, captured_run, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert main(["--fps", "30", "--no-cursor", "--windowed"]) == 0
        settings = captured_run[0]
        assert settings.fps == 30
        assert settings.cursor is False
        assert settings.windowed is True

    def test_config_file_applies_and_cli_wins(self, captured_run, tmp_path: Path):
        config = tmp_path / "config.toml"
        config.write_text("fps = 24\nscale = 'fast'\n", encoding="utf-8")
        assert main(["--config", str(config), "--fps", "48"]) == 0
        settings = captured_run[0]
        assert settings.fps == 48  # CLI beats file
        assert settings.scale == "fast"  # file beats default

    def test_missing_explicit_config_errors(self, capsys: pytest.CaptureFixture, tmp_path):
        assert main(["--config", str(tmp_path / "nope.toml")]) == 2
        assert "config file not found" in capsys.readouterr().err

    def test_errors_reach_the_log_file_under_pythonw(self, monkeypatch, tmp_path):
        """uwmirrorw has no stderr; startup errors must not vanish silently."""
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.setattr(sys, "stderr", None)
        assert main(["--config", str(tmp_path / "nope.toml")]) == 2
        logged = (tmp_path / "uwmirror" / "uwmirror.log").read_text(encoding="utf-8")
        assert "config file not found" in logged

    def test_invalid_flag_value_reports_config_error(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert main(["--fps", "0"]) == 2
        assert "fps" in capsys.readouterr().err

    def test_invalid_hotkey_spec_reports_error(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert main(["--pause-hotkey", "banana"]) == 2
        assert "banana" in capsys.readouterr().err

    def test_diagnose_dispatch(self, monkeypatch: pytest.MonkeyPatch):
        import uwmirror.diagnose as diagnose_module

        calls: list[str] = []
        monkeypatch.setattr(diagnose_module, "run", lambda backend: calls.append(backend) or 0)
        assert main(["diagnose"]) == 0
        assert calls == ["dxcam"]


class TestPlatformGate:
    def test_non_windows_exits_with_message(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "platform", "linux")
        assert main([]) == 2
        assert "Windows" in capsys.readouterr().err
