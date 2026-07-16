from __future__ import annotations

from animetta.config.user import UserSettings

"""Tests for UserSettings (config.user.py)"""

import sys
from pathlib import Path
from unittest.mock import mock_open, patch

# Ensure src/ is on the Python path
_src_path = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)


# ═══════════════════════════════════════════════════════════════
# Test UserSettings
# ═══════════════════════════════════════════════════════════════


class TestUserSettingsInit:
    """Tests for UserSettings.__init__"""

    @patch("animetta.config.user.UserSettings._load")
    def test_creates_config_file_from_root_dir(self, mock_load):
        """__init__ stores config_file as root_dir/.user_settings.yaml"""
        mock_load.return_value = {"log_level": "INFO"}
        root = Path("/fake/root")
        settings = UserSettings(root)

        expected_path = root / ".user_settings.yaml"
        assert settings.config_file == expected_path

    @patch("animetta.config.user.UserSettings._load")
    def test_calls_load_on_init(self, mock_load):
        """__init__ calls _load to populate settings"""
        mock_load.return_value = {"log_level": "DEBUG"}
        root = Path("/fake/root")
        settings = UserSettings(root)

        mock_load.assert_called_once()
        assert settings.settings == {"log_level": "DEBUG"}


class TestUserSettingsLoad:
    """Tests for UserSettings._load"""

    @patch("pathlib.Path.exists", return_value=False)
    def test_returns_defaults_when_file_missing(self, mock_exists):
        """_load returns default settings when config file doesn't exist"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")

        result = settings._load()

        assert result == {"log_level": "INFO"}

    @patch("builtins.open", new_callable=mock_open, read_data="log_level: DEBUG\n")
    @patch("pathlib.Path.exists", return_value=True)
    def test_loads_yaml_when_file_exists(self, mock_exists, mock_file):
        """_load reads and parses YAML from the config file"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")

        result = settings._load()

        assert result == {"log_level": "DEBUG"}

    @patch("builtins.open", side_effect=PermissionError("denied"))
    @patch("pathlib.Path.exists", return_value=True)
    def test_falls_back_on_read_error(self, mock_exists, mock_open_file):
        """_load returns defaults when reading the file raises an exception"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")

        result = settings._load()

        assert result == {"log_level": "INFO"}

    @patch("builtins.open", new_callable=mock_open, read_data="invalid: [yaml\n")
    @patch("pathlib.Path.exists", return_value=True)
    def test_falls_back_on_yaml_parse_error(self, mock_exists, mock_file):
        """_load returns defaults when YAML parsing fails"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")

        result = settings._load()

        assert result == {"log_level": "INFO"}

    @patch("builtins.open", new_callable=mock_open, read_data="")
    @patch("pathlib.Path.exists", return_value=True)
    def test_handles_empty_file(self, mock_exists, mock_file):
        """_load returns {} for empty file (safe_load returns None)"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")

        result = settings._load()

        assert result == {}


class TestUserSettingsCreateDefault:
    """Tests for UserSettings._create_default"""

    def test_returns_default_dict(self):
        """_create_default returns default settings dict"""
        settings = UserSettings.__new__(UserSettings)
        result = settings._create_default()
        assert result == {"log_level": "INFO"}

    def test_returns_new_dict_each_call(self):
        """_create_default returns a new dict each time (not the same object)"""
        settings = UserSettings.__new__(UserSettings)
        result1 = settings._create_default()
        result2 = settings._create_default()
        assert result1 is not result2
        assert result1 == result2


class TestUserSettingsSave:
    """Tests for UserSettings.save"""

    @patch("builtins.open", new_callable=mock_open)
    @patch("yaml.safe_dump")
    def test_writes_yaml_to_file(self, mock_safe_dump, mock_file):
        """save writes settings as YAML to the config file"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")
        settings.settings = {"log_level": "WARN"}

        settings.save()

        mock_file.assert_called_once_with(settings.config_file, "w", encoding="utf-8")
        mock_safe_dump.assert_called_once_with(
            {"log_level": "WARN"}, mock_file(), allow_unicode=True
        )

    @patch("builtins.open", side_effect=OSError("disk full"))
    @patch("yaml.safe_dump")
    def test_handles_write_error(self, mock_safe_dump, mock_file):
        """save does not raise when writing fails (logs error)"""
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/fake/.user_settings.yaml")
        settings.settings = {"log_level": "DEBUG"}

        # Should not raise
        settings.save()


class TestUserSettingsGetLogLevel:
    """Tests for UserSettings.get_log_level"""

    @patch("animetta.config.user.UserSettings._load")
    def test_returns_from_settings(self, mock_load):
        """get_log_level returns the currently configured log level"""
        mock_load.return_value = {"log_level": "DEBUG"}
        settings = UserSettings(Path("/fake/root"))

        assert settings.get_log_level() == "DEBUG"

    @patch("animetta.config.user.UserSettings._load")
    def test_returns_default_when_not_set(self, mock_load):
        """get_log_level returns 'INFO' when level not in settings"""
        mock_load.return_value = {}
        # Simulate settings dict without log_level
        settings = UserSettings.__new__(UserSettings)
        settings.settings = {}

        assert settings.get_log_level() == "INFO"

    def test_default_init_log_level_is_info(self):
        """New UserSettings with default load returns 'INFO'"""
        # Use isolated instance to avoid file system
        settings = UserSettings.__new__(UserSettings)
        settings.config_file = Path("/nonexistent/.user_settings.yaml")
        settings.settings = {"log_level": "INFO"}

        assert settings.get_log_level() == "INFO"


class TestUserSettingsSetLogLevel:
    """Tests for UserSettings.set_log_level"""

    @patch("animetta.config.user.UserSettings.save")
    def test_updates_setting_and_calls_save(self, mock_save):
        """set_log_level updates the setting and calls save"""
        settings = UserSettings.__new__(UserSettings)
        settings.settings = {"log_level": "INFO"}

        settings.set_log_level("ERROR")

        assert settings.settings["log_level"] == "ERROR"
        mock_save.assert_called_once()

    @patch("animetta.config.user.UserSettings.save")
    def test_save_called_after_update(self, mock_save):
        """save is called exactly once after setting log level"""
        settings = UserSettings.__new__(UserSettings)
        settings.settings = {"log_level": "INFO"}

        settings.set_log_level("DEBUG")

        assert mock_save.call_count == 1

    @patch("animetta.config.user.UserSettings.save")
    def test_round_trip(self, mock_save):
        """set_log_level then get_log_level returns the new value"""
        settings = UserSettings.__new__(UserSettings)
        settings.settings = {"log_level": "INFO"}

        settings.set_log_level("WARN")
        assert settings.get_log_level() == "WARN"
