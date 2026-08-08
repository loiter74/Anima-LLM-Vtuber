from __future__ import annotations

"""Tests for AutoConfig — environment detection, config generation."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from animetta.utils.auto_config import AutoConfig


@pytest.fixture
def auto_config():
    config = AutoConfig.__new__(AutoConfig)
    config.project_root = Path.cwd()
    config.env_info = {
        "platform": "windows",
        "python_version": "3.13",
        "python_executable": "py -3.13",
        "gpu_available": False,
        "cuda_version": None,
        "data_dir_exists": False,
        "models_exist": False,
    }
    config.issues = []
    config.warnings = []
    return config


class TestAutoConfig:
    """Suite for AutoConfig detection and generation functions."""

    # ── _detect_platform ─────────────────────────────────────────────

    def test_detect_platform_windows(self, auto_config):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(os.environ, {}, clear=True),
        ):
            assert auto_config._detect_platform() == "windows"

    def test_detect_platform_wsl(self, auto_config):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=True),
        ):
            assert auto_config._detect_platform() == "wsl"

    def test_detect_platform_linux(self, auto_config):
        with (
            patch("platform.system", return_value="Linux"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            assert auto_config._detect_platform() == "linux"

    def test_detect_platform_macos(self, auto_config):
        with patch("platform.system", return_value="Darwin"):
            assert auto_config._detect_platform() == "macos"

    def test_detect_platform_unknown(self, auto_config):
        with patch("platform.system", return_value="SomeOS"):
            assert auto_config._detect_platform() == "unknown"

    # ── _check_gpu ───────────────────────────────────────────────────

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

    def test_get_data_dir_windows_default(self, auto_config):
        """Windows fallback: E:/animetta_data or home/animetta_data."""
        auto_config.env_info["platform"] = "windows"
        with patch("pathlib.Path.exists", return_value=False):
            result = auto_config.get_data_dir()
        assert result == Path.home() / "animetta_data"

    def test_get_data_dir_windows_e_drive(self, auto_config):
        """On Windows, E:/animetta_data takes priority if it exists."""
        auto_config.env_info["platform"] = "windows"
        with patch("pathlib.Path.exists", return_value=True):
            result = auto_config.get_data_dir()
        assert result == Path("E:/animetta_data")

    def test_get_data_dir_linux_default(self, auto_config):
        """Linux/macOS fallback: ~/animetta_data."""
        auto_config.env_info["platform"] = "linux"
        result = auto_config.get_data_dir()
        assert result == Path.home() / "animetta_data"

    # ── check_dependencies ───────────────────────────────────────────

    def test_diagnose_missing_deps(self, auto_config):
        """Missing dependencies should make diagnose return False."""
        with (
            patch.multiple(
                auto_config,
                get_data_dir=MagicMock(return_value=Path("/tmp")),
                check_dependencies=MagicMock(return_value=(False, ["fastapi"])),
            ),
            patch("pathlib.Path.exists", return_value=True),
        ):
            result = auto_config.diagnose()
            assert result is False

    # ── setup_all ────────────────────────────────────────────────────

    def test_generate_env_file_copies_canonical_example_without_business_overrides(
        self, auto_config, tmp_path
    ):
        auto_config.project_root = tmp_path
        canonical = (
            "ANIMETTA_PROFILE=test\n"
            "ANIMETTA_HOST=127.0.0.1\n"
            "ANIMETTA_PORT=12394\n"
            "DEEPSEEK_API_KEY=\n"
        )
        (tmp_path / ".env.example").write_text(canonical, encoding="utf-8")

        generated = auto_config.generate_env_file()

        assert generated.read_text(encoding="utf-8") == canonical
        assert "ANIMETTA_BASE_MODEL_PATH" not in generated.read_text(encoding="utf-8")
        assert "ANIMETTA_LORA_PATH" not in generated.read_text(encoding="utf-8")

    def test_setup_all_never_generates_a_secondary_provider_config(self, auto_config):
        assert not hasattr(auto_config, "generate_local_lora_config")
        with (
            patch.object(auto_config, "generate_env_file"),
            patch.object(auto_config, "setup_data_dir"),
        ):
            assert auto_config.setup_all(auto_fix=False) is True

    def test_setup_all_no_auto_fix(self, auto_config):
        """setup_all(auto_fix=False) should not install dependencies."""
        with patch.multiple(
            auto_config,
            generate_env_file=MagicMock(),
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
        with (
            patch.object(auto_config, "check_dependencies", return_value=(False, ["missing"])),
            patch("subprocess.check_call", side_effect=Exception("pip error")),
        ):
            result = auto_config.auto_install_dependencies()
            assert result is False
