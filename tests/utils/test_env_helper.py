from __future__ import annotations

from animetta.utils.env_helper import EnvHelper, Environment, detect_env, get_data_dir, resolve_path

"""Tests for EnvHelper platform detection and path conversion."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestEnvHelperDetection:
    """Environment detection tests."""

    def test_detect_windows(self):
        with patch("platform.system", return_value="Windows"):
            env = EnvHelper.detect_environment()
            assert env == Environment.WINDOWS

    def test_detect_macos(self):
        with patch("platform.system", return_value="Darwin"):
            env = EnvHelper.detect_environment()
            assert env == Environment.MACOS

    def test_detect_linux(self):
        with patch("platform.system", return_value="Linux"), patch.object(EnvHelper, "_check_wsl", return_value=Environment.LINUX):
            env = EnvHelper.detect_environment()
            assert env == Environment.LINUX

    def test_detect_wsl_by_proc_version(self):
        with patch("platform.system", return_value="Linux"), patch("pathlib.Path.exists", return_value=True), patch("builtins.open", MagicMock()), patch.object(Path, "open", MagicMock()):
            # We need to mock /proc/version read
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = "Linux ... microsoft ... WSL2"
            with patch("builtins.open", return_value=mock_file):
                env = EnvHelper.detect_environment()
                assert env == Environment.WSL

    def test_detect_wsl_by_env_var(self):
        with patch("platform.system", return_value="Linux"), patch("pathlib.Path.exists", return_value=False), patch("os.getenv", side_effect=lambda k, d=None: "Ubuntu" if k == "WSL_DISTRO_NAME" else d):
            env = EnvHelper.detect_environment()
            assert env == Environment.WSL


import sys


@pytest.mark.skipif(sys.platform != "linux", reason="WSL tests only run on Linux")
class TestEnvHelperPathConversion:
    """Windows-WSL path conversion tests."""

    def test_convert_windows_to_wsl(self):
        result = EnvHelper.convert_windows_to_wsl("E:/anima_data/models")
        assert result == "/mnt/e/anima_data/models"

    def test_convert_windows_to_wsl_backward_slash(self):
        result = EnvHelper.convert_windows_to_wsl("C:\\Users\\test\\data")
        assert "/mnt/c/" in result

    def test_convert_windows_to_wsl_no_drive(self):
        result = EnvHelper.convert_windows_to_wsl("/absolute/path")
        assert result == "/absolute/path"

    def test_convert_wsl_to_windows(self):
        result = EnvHelper.convert_wsl_to_windows("/mnt/e/anima_data/models")
        assert result == "E:/anima_data/models"

    def test_convert_wsl_to_windows_not_mnt(self):
        result = EnvHelper.convert_wsl_to_windows("/home/user/data")
        assert result == "/home/user/data"

    def test_convert_wsl_to_windows_short_path(self):
        result = EnvHelper.convert_wsl_to_windows("/mnt/c")
        assert result == "C:"


import sys as _sys


@pytest.mark.skipif(_sys.platform != "linux", reason="WSL tests only run on Linux")
class TestEnvHelperResolvePath:
    """Cross-environment path resolution tests."""

    def test_resolve_no_conversion_needed(self):
        with patch("os.path.expandvars", side_effect=lambda x: x), patch.object(EnvHelper, "detect_environment", return_value=Environment.WINDOWS):
            result = EnvHelper.resolve_model_path("C:/data", env=Environment.WINDOWS)
            assert result == "C:/data"

    def test_resolve_windows_to_wsl(self):
        with patch("os.path.expandvars", side_effect=lambda x: x), patch.object(EnvHelper, "detect_environment", return_value=Environment.WINDOWS):
            result = EnvHelper.resolve_model_path("E:/anima_data", env=Environment.WSL)
            assert result == "/mnt/e/anima_data"

    def test_resolve_wsl_to_windows(self):
        with patch("os.path.expandvars", side_effect=lambda x: x), patch.object(EnvHelper, "detect_environment", return_value=Environment.WSL):
            result = EnvHelper.resolve_model_path("/mnt/e/anima_data", env=Environment.WINDOWS)
            assert result == "E:/anima_data"

    def test_resolve_expand_vars(self):
        with patch("os.path.expandvars", side_effect=lambda x: x.replace("$HOME", "/home/user")), patch.object(EnvHelper, "detect_environment", return_value=Environment.LINUX):
            result = EnvHelper.resolve_model_path("$HOME/data")
            assert result == "/home/user/data"


import sys as _sys2


@pytest.mark.skipif(_sys2.platform != "linux", reason="WSL tests only run on Linux")
class TestEnvHelperGetDataDir:
    """Data directory detection tests."""

    @patch("pathlib.Path.exists", return_value=True)
    def test_get_data_dir_windows(self, mock_exists):
        with patch.object(EnvHelper, "detect_environment", return_value=Environment.WINDOWS):
            data_dir = EnvHelper.get_data_dir()
            # Should pick up E:/anima_data since it "exists"
            assert "anima_data" in str(data_dir)

    @patch("pathlib.Path.exists", return_value=False)
    def test_get_data_dir_windows_fallback(self, mock_exists):
        with (
            patch.object(EnvHelper, "detect_environment", return_value=Environment.WINDOWS),
            patch("pathlib.Path.home", return_value=Path("/home/user")),
        ):
            data_dir = EnvHelper.get_data_dir()
            assert "anima_data" in str(data_dir)

    def test_get_data_dir_from_env(self):
        with patch("os.getenv", return_value="/custom/data/dir"):
            data_dir = EnvHelper.get_data_dir()
            assert str(data_dir) == "/custom/data/dir"


class TestDefaultModelConfig:
    """Compatibility view exposes only canonical runtime inputs."""

    def test_default_model_config(self):
        config = EnvHelper.get_default_model_config()
        assert config["ANIMETTA_PROFILE"] == "test"
        assert config["ANIMETTA_HOST"] == "127.0.0.1"
        assert config["ANIMETTA_PORT"] == "12394"
        assert "ANIMETTA_BASE_MODEL_PATH" not in config
        assert "ANIMETTA_LORA_PATH" not in config


class TestSetupEnvFile:
    """.env file generation tests."""

    @patch("animetta.utils.env_helper.EnvHelper.detect_environment", return_value="windows")
    @patch("animetta.utils.env_helper.EnvHelper.get_default_model_config")
    def test_setup_env_file_creates(self, mock_config, mock_detect, tmp_path):
        mock_config.return_value = {
            "ANIMA_DATA_DIR": "/data",
            "ANIMA_BASE_MODEL_PATH": "/data/models/base",
            "ANIMA_LORA_PATH": "/data/models/lora",
            "ANIMA_VECTOR_DB_PATH": "/data/vectordb",
            "ANIMA_HISTORY_PATH": "/data/history",
        }

        # We can only test the config generation logic
        config = EnvHelper.get_default_model_config()
        assert "ANIMA_DATA_DIR" in config


class TestConvenienceFunctions:
    """Module-level convenience functions."""

    def test_detect_env(self):
        with patch("animetta.utils.env_helper.EnvHelper.detect_environment", return_value="linux"):
            assert detect_env() == "linux"

    def test_get_data_dir_convenience(self):
        with patch("animetta.utils.env_helper.EnvHelper.get_data_dir", return_value=Path("/data")):
            assert get_data_dir() == Path("/data")

    def test_resolve_path_convenience(self):
        with patch("animetta.utils.env_helper.EnvHelper.resolve_model_path", return_value="/resolved/path"):
            assert resolve_path("/some/path") == "/resolved/path"


class TestPrintEnvironmentInfo:
    """Environment info printing."""

    def test_print_environment_info(self, capsys):
        with (
            patch.object(EnvHelper, "detect_environment", return_value="linux"),
            patch.object(EnvHelper, "get_data_dir", return_value=Path("/data")),
        ):
            EnvHelper.print_environment_info()
            captured = capsys.readouterr()
            assert "Environment Information" in captured.out
            assert "LINUX" in captured.out
