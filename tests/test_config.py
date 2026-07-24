from pathlib import Path

import pytest

from uwmirror.config import ConfigError, Settings, default_config_path, load_toml, resolve


class TestResolve:
    def test_defaults(self):
        settings = resolve({}, {})
        assert settings == Settings()
        assert settings.fps == 15
        assert settings.scale == "smooth"
        assert settings.cursor is True
        assert settings.tray is True
        assert settings.quit_hotkey == "ctrl+alt+q"
        assert settings.source is None

    def test_file_overrides_defaults(self):
        settings = resolve({}, {"fps": 30, "cursor": False})
        assert settings.fps == 30
        assert settings.cursor is False

    def test_cli_overrides_file(self):
        settings = resolve({"fps": 120}, {"fps": 30})
        assert settings.fps == 120

    def test_cli_none_falls_through_to_file(self):
        settings = resolve({"fps": None}, {"fps": 30})
        assert settings.fps == 30

    def test_explicit_false_from_cli_wins(self):
        settings = resolve({"cursor": False}, {"cursor": True})
        assert settings.cursor is False


class TestValidation:
    @pytest.mark.parametrize("fps", [0, -1, 241, "sixty", True])
    def test_bad_fps(self, fps):
        with pytest.raises(ConfigError, match="fps"):
            resolve({"fps": fps}, {})

    def test_bad_scale(self):
        with pytest.raises(ConfigError, match="scale"):
            resolve({"scale": "bicubic"}, {})

    def test_bad_backend(self):
        with pytest.raises(ConfigError, match="backend"):
            resolve({"backend": "obs"}, {})

    def test_bad_log_level(self):
        with pytest.raises(ConfigError, match="log_level"):
            resolve({"log_level": "loud"}, {})

    @pytest.mark.parametrize("value", [-1, "one", True])
    def test_bad_source(self, value):
        with pytest.raises(ConfigError, match="source"):
            resolve({"source": value}, {})

    def test_bad_bool_option(self):
        with pytest.raises(ConfigError, match="windowed"):
            resolve({}, {"windowed": 1})

    def test_bad_tray_option(self):
        with pytest.raises(ConfigError, match="tray"):
            resolve({}, {"tray": "yes"})

    def test_bad_hotkey_type(self):
        with pytest.raises(ConfigError, match="pause_hotkey"):
            resolve({}, {"pause_hotkey": 5})

    def test_bad_quit_hotkey_type(self):
        with pytest.raises(ConfigError, match="quit_hotkey"):
            resolve({}, {"quit_hotkey": 5})


class TestLoadToml:
    def test_loads_and_normalizes_kebab_keys(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text('fps = 30\n"pause-hotkey" = "ctrl+alt+f9"\n', encoding="utf-8")
        cfg = load_toml(path)
        assert cfg == {"fps": 30, "pause_hotkey": "ctrl+alt+f9"}

    def test_unknown_key_lists_valid_options(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text("framerate = 30\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="framerate") as excinfo:
            load_toml(path)
        assert "fps" in str(excinfo.value)  # the error suggests valid keys

    def test_invalid_toml(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text("fps = = 30\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="invalid TOML"):
            load_toml(path)

    def test_roundtrip_through_resolve(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text("source = 0\ntarget = 1\nfps = 30\n", encoding="utf-8")
        settings = resolve({}, load_toml(path))
        assert (settings.source, settings.target, settings.fps) == (0, 1, 30)


class TestDefaultConfigPath:
    def test_uses_appdata(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert default_config_path() == tmp_path / "uwmirror" / "config.toml"

    def test_falls_back_to_home(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("APPDATA", raising=False)
        assert default_config_path() == Path.home() / "uwmirror" / "config.toml"
