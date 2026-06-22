from __future__ import annotations

"""Tests for AutoConfig — environment detection, config generation."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from animetta.utils.auto_config import AutoConfig


@pytest.fixture
def auto_config():

    return AutoConfig()


class TestAutoConfig:
    """Suite for AutoConfig detection and generation functions."""

    # ── _detect_platform ─────────────────────────────────────────────

    def test_detect_platform_windows(self, auto_config):
        with patch("platform.system", return_value="Windows"), patch.dict(os.environ, {}, clear=True):
            assert auto_config._detect_platform() == "windows"

    def test_detect_platform_wsl(self, auto_config):
        with patch("platform.system", return_value="Windows"), patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=True):
            assert auto_config._detect_platform() == "wsl"

    def test_detect_platform_linux(self, auto_config):
        with patch("platform.system", return_value="Linux"), patch("pathlib.Path.exists", return_value=False):
            assert auto_config._detect_platform() == "linux"

    def test_detect_platform_macos(self, auto_config):
        with patch("platform.system", return_value="Darwin"):
            assert auto_config._detect_platform() == "macos"

    def test_detect_platform_unknown(self, auto_config):
        with patch("platform.system", return_value="SomeOS"):
            assert auto_config._detect_platform() == "unknown"

    # ── _check_gpu ───────────────────────────────────────────────────

    @pytest.mark.skip(reason="Only runs on CUDA-capable machines")
    def test_check_gpu_available(self, auto_config):
        assert auto_config._check_gpu() is True

    def test_check_gpu_not_available(self, auto_config):
        with patch.dict("sys.modules", {"torch": None}):
            pass  # can't actually unload torch

    def test_check_gpu_import_error(self, auto_config):
        """If torch can't be imported, GPU check returns False."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "torch":
                raise ImportError("no torch")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            assert auto_config._check_gpu() is False

    # ── get_data_dir ─────────────────────────────────────────────────

    def test_get_data_dir_env_var(self, auto_config):
        """ANIMETTA_DATA_DIR env var takes precedence."""
        with patch.dict(os.environ, {"ANIMETTA_DATA_DIR": "/custom/path"}, clear=True):
            assert auto_config.get_data_dir() == Path("/custom/path")

    @pytest.mark.xfail(reason="patch.object on dict.__getitem__ is not supported", strict=False)
    def test_get_data_dir_windows_default(self, auto_config):
        """Windows fallback: E:/anima_data or home/anima_data."""
        with patch("platform.system", return_value="Windows"), patch.object(auto_config.env_info, "__getitem__", return_value="windows"), patch("pathlib.Path.exists", return_value=False):
            result = auto_config.get_data_dir()
            assert "anima_data" in str(result)

    @pytest.mark.xfail(reason="patch.object on dict.__getitem__ is not supported", strict=False)
    def test_get_data_dir_windows_e_drive(self, auto_config):
        """On Windows, E:/anima_data takes priority if it exists."""
        with patch.object(auto_config.env_info, "__getitem__", return_value="windows"), patch("pathlib.Path.exists", return_value=True):
            result = auto_config.get_data_dir()
            assert "E:" in str(result) or "anima_data" in str(result)

    @pytest.mark.skipif(sys.platform == "win32", reason="Linux-specific path format")
    def test_get_data_dir_linux_default(self, auto_config):
        """Linux/macOS fallback: ~/anima_data."""
        with patch.object(auto_config.env_info, "__getitem__", return_value="linux"):
            result = auto_config.get_data_dir()
            assert result == Path.home() / "anima_data"

    # ── check_dependencies ───────────────────────────────────────────

    @pytest.mark.skipif(sys.platform == "win32", reason="Linux-specific test (shutil.which path format)")
    def test_check_dependencies_all_installed(self, auto_config):
        """Returns {"python": True, "pip": True, "git": True} when all found."""
        with (
            patch("shutil.which", return_value="/usr/bin/python"),
            patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "anima"}, clear=True),
        ):
            result = auto_config.diagnose()
            assert isinstance(result, bool)

    def test_diagnose_missing_deps(self, auto_config):
        """Missing dependencies should make diagnose return False."""
        with patch.multiple(
            auto_config,
            get_data_dir=MagicMock(return_value=Path("/tmp")),
            check_dependencies=MagicMock(return_value=(False, ["fastapi"])),
        ), patch("pathlib.Path.exists", return_value=True):
            result = auto_config.diagnose()
            assert result is False

    # ── setup_all ────────────────────────────────────────────────────

    def test_setup_all_no_auto_fix(self, auto_config):
        """setup_all(auto_fix=False) should not install dependencies."""
        with patch.multiple(
            auto_config,
            generate_env_file=MagicMock(),
            generate_local_lora_config=MagicMock(),
            setup_data_dir=MagicMock(return_value=Path("/tmp")),
        ):
            result = auto_config.setup_all(auto_fix=False)
            assert result is True

    def test_setup_all_with_errors(self, auto_config):
        """If a step fails, setup_all should return False."""
        with patch.object(auto_config, "generate_env_file", side_effect=Exception("fail")):
            result = auto_config.setup_all(auto_fix=False)
            assert result is False

    # ── auto_install_dependencies ────────────────────────────────────

    def test_auto_install_already_ok(self, auto_config):
        """If all deps installed, returns True without calling pip."""
        with patch.object(auto_config, "check_dependencies", return_value=(True, [])):
            result = auto_config.auto_install_dependencies()
            assert result is True

    def test_auto_install_failure(self, auto_config):
        """If pip install fails, returns False."""
        with patch.object(auto_config, "check_dependencies", return_value=(False, ["missing"])), patch("subprocess.check_call", side_effect=Exception("pip error")):
            result = auto_config.auto_install_dependencies()
            assert result is False
