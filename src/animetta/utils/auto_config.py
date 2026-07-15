"""
Auto environment configuration module
One-click environment detection, config generation, dependency installation
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

from loguru import logger


class AutoConfig:
    """Auto environment configurator"""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent.parent
        self.env_info = self._detect_all()
        self.issues = []
        self.warnings = []

    def _detect_all(self) -> dict:
        """Detect all environment information"""
        return {
            "platform": self._detect_platform(),
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "gpu_available": self._check_gpu(),
            "cuda_version": self._get_cuda_version(),
            "data_dir_exists": False,
            "models_exist": False,
        }

    def _detect_platform(self) -> str:
        """Detect platform"""
        system = platform.system().lower()

        if system == "windows":
            # Check if WSL (via environment variable)
            if os.getenv("WSL_DISTRO_NAME") or os.getenv("WSLENV"):
                return "wsl"
            return "windows"
        elif system == "linux":
            # Check WSL
            if Path("/proc/version").exists():
                try:
                    with open("/proc/version") as f:
                        if "microsoft" in f.read().lower():
                            return "wsl"
                except Exception:
                    logger.debug("[AutoConfig] Failed to read /proc/version for WSL detection")
            return "linux"
        elif system == "darwin":
            return "macos"

        return "unknown"

    def _check_gpu(self) -> bool:
        """Check GPU availability"""
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    def _get_cuda_version(self) -> str | None:
        """Get CUDA version"""
        try:
            import torch

            if torch.cuda.is_available():
                return torch.version.cuda
        except Exception:
            logger.debug("[AutoConfig] Failed to get CUDA version")
        return None

    def get_data_dir(self) -> Path:
        """Intelligently get data directory"""
        platform_name = self.env_info["platform"]

        # 1. Check environment variable
        env_dir = os.getenv("ANIMETTA_DATA_DIR")
        if env_dir:
            return Path(env_dir)

        # 2. Select default location based on platform
        if platform_name == "windows":
            # Windows: E:/animetta_data or C:/Users/xxx/animetta_data
            e_drive = Path("E:/animetta_data")
            if e_drive.exists():
                return e_drive
            return Path.home() / "animetta_data"

        elif platform_name == "wsl":
            # WSL: prefer /mnt/e (shared data), fallback to ~/animetta_data
            mnt_e = Path("/mnt/e/animetta_data")
            if mnt_e.exists():
                return mnt_e
            return Path.home() / "animetta_data"

        else:  # linux, macos
            return Path.home() / "animetta_data"

    def check_dependencies(self) -> tuple[bool, list[str]]:
        """Check if dependencies are installed"""
        missing = []
        required_packages = [
            "starlette",
            "pydantic",
            "loguru",
            "yaml",
            "socketio",
        ]

        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)

        return len(missing) == 0, missing

    def generate_env_file(self, force: bool = False) -> Path:
        """Copy the canonical endpoint/secret template to ``.env``."""
        env_file = self.project_root / ".env"

        if env_file.exists() and not force:
            logger.info(f"✅ .env file already exists: {env_file}")
            return env_file

        example = self.project_root / ".env.example"
        if not example.is_file():
            raise FileNotFoundError("Canonical .env.example is missing")
        env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info(f"✅ .env file generated: {env_file}")

        return env_file

    def setup_data_dir(self) -> Path:
        """Create data directory structure"""
        data_dir = self.get_data_dir()

        # Create directory structure
        dirs = [
            data_dir,
            data_dir / "models" / "base_models",
            data_dir / "models" / "checkpoints",
            data_dir / "vectordb",
            data_dir / "histories",
        ]

        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"✅ Data directory created: {data_dir}")

        return data_dir

    def auto_install_dependencies(self) -> bool:
        """Auto-install dependencies"""
        success = True

        try:
            logger.info("📦 Checking dependencies...")

            # Check basic dependencies
            all_ok, missing = self.check_dependencies()

            if all_ok:
                logger.info("✅ All dependencies installed")
                return True

            logger.warning(f"⚠️  Missing dependencies: {', '.join(missing)}")
            logger.info("📦 Installing...")

            # Install dependencies
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(self.project_root / "requirements.txt"),
                    "--quiet",
                ]
            )

            logger.info("✅ Dependencies installed")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Dependency installation failed: {e}")
            success = False
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            success = False

        return success

    def diagnose(self) -> bool:
        """Diagnose the environment, return whether ready"""
        logger.info("=" * 60)
        logger.info("  Animetta Environment Diagnostics")
        logger.info("=" * 60)

        all_ok = True

        # 1. Platform information
        logger.info(f"📌 Platform: {self.env_info['platform'].upper()}")
        logger.info(f"🐍 Python: {self.env_info['python_version']}")
        logger.info("")

        # 2. GPU detection
        if self.env_info["gpu_available"]:
            logger.info(f"✅ GPU: Available (CUDA {self.env_info['cuda_version']})")
        else:
            logger.warning("⚠️  GPU: Not available (will use CPU, slower)")
            all_ok = False
        logger.info("")

        # 3. Data directory
        data_dir = self.get_data_dir()
        if data_dir.exists():
            logger.info(f"✅ Data directory: {data_dir}")
        else:
            logger.warning(f"⚠️  Data directory does not exist: {data_dir}")
            all_ok = False
        logger.info("")

        # 4. Dependency check
        deps_ok, missing = self.check_dependencies()
        if deps_ok:
            logger.info("✅ Python dependencies: Complete")
        else:
            logger.warning(f"⚠️  Python dependencies: Missing {', '.join(missing)}")
            all_ok = False
        logger.info("")

        # 5. Configuration file
        env_file = self.project_root / ".env"
        if env_file.exists():
            logger.info(f"✅ Configuration file: {env_file}")
        else:
            logger.warning(f"⚠️  Configuration file does not exist: {env_file}")
            all_ok = False
        logger.info("")

        logger.info("=" * 60)

        return all_ok

    def setup_all(self, auto_fix: bool = True) -> bool:
        """One-click setup of all environments"""
        logger.info("🚀 Starting auto configuration...")

        success = True

        # 1. Generate .env
        try:
            self.generate_env_file(force=False)
        except Exception as e:
            logger.error(f"❌ Failed to generate .env: {e}")
            success = False

        # 2. Create data directory
        try:
            self.setup_data_dir()
        except Exception as e:
            logger.error(f"❌ Failed to create directory: {e}")
            success = False

        # 3. Install dependencies
        if auto_fix and not self.auto_install_dependencies():
            success = False

        return success


def main():
    """Command line entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Animetta 自动环境配置")
    parser.add_argument("--check", action="store_true", help="检查环境")
    parser.add_argument("--setup", action="store_true", help="自动配置环境")
    parser.add_argument("--force", action="store_true", help="强制覆盖配置")

    args = parser.parse_args()

    auto_config = AutoConfig()

    if args.check:
        ready = auto_config.diagnose()
        sys.exit(0 if ready else 1)

    elif args.setup:
        success = auto_config.setup_all(auto_fix=True)
        if success:
            logger.info("")
            logger.info("✅ Environment configuration complete!")
            logger.info("")
            logger.info("Next step: python -m animetta.core.socketio_server")
        sys.exit(0 if success else 1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
