"""
Environment detection and path mapping utility
Environment Detection and Path Mapping Utility

Auto-detect the current runtime environment and provide cross-platform path conversion
"""

import os
import platform
import sys
from pathlib import Path

from loguru import logger


class Environment:
    """Environment type constants"""

    WINDOWS = "windows"
    WSL = "wsl"
    LINUX = "linux"
    MACOS = "macos"


class EnvHelper:
    """Environment helper utility class"""

    @staticmethod
    def detect_environment() -> str:
        """
        Detect the current runtime environment

        Returns:
            str: Environment type (windows/wsl/linux/macos)
        """
        system = platform.system().lower()

        if system == "windows":
            return Environment.WINDOWS
        elif system == "darwin":
            return Environment.MACOS
        elif system == "linux":
            # Check if running under WSL
            return EnvHelper._check_wsl()

        return Environment.LINUX

    @staticmethod
    def _check_wsl() -> str:
        """
        Detect if running in WSL environment

        Returns:
            str: wsl or linux
        """
        try:
            # Method 1: Check /proc/version
            if Path("/proc/version").exists():
                with open("/proc/version") as f:
                    version_info = f.read().lower()
                    if "microsoft" in version_info or "wsl" in version_info:
                        return Environment.WSL
        except Exception:
            pass

        # Method 2: Check environment variable
        if os.getenv("WSL_DISTRO_NAME") or os.getenv("WSLENV"):
            return Environment.WSL

        return Environment.LINUX

    @staticmethod
    def convert_windows_to_wsl(windows_path: str) -> str:
        """
        Convert Windows path to WSL path

        Args:
            windows_path: Windows path (e.g. E:/animetta_data)

        Returns:
            str: WSL path (e.g. /mnt/e/animetta_data)

        Example:
            >>> EnvHelper.convert_windows_to_wsl("E:/animetta_data/models")
            "/mnt/e/animetta_data/models"
        """
        path = Path(windows_path)

        # Handle Windows drive letter
        if len(path.parts) >= 1 and len(path.parts[0]) == 2 and path.parts[0][1] == ":":
            drive = path.parts[0][0].lower()
            rest = path.as_posix()[3:]  # Strip "X:/"
            return f"/mnt/{drive}/{rest}"

        return path.as_posix()

    @staticmethod
    def convert_wsl_to_windows(wsl_path: str) -> str:
        """
        Convert WSL path to Windows path

        Args:
            wsl_path: WSL path (e.g. /mnt/e/animetta_data)

        Returns:
            str: Windows path (e.g. E:\\animetta_data)

        Example:
            >>> EnvHelper.convert_wsl_to_windows("/mnt/e/animetta_data/models")
            "E:\\animetta_data\\models"
        """
        path = wsl_path

        # Handle /mnt/X/ format
        if path.startswith("/mnt/"):
            parts = path.split("/")
            if len(parts) >= 3:
                drive = parts[2].upper()
                rest = "/".join(parts[3:])
                return f"{drive}:/{rest}"

        return path

    @staticmethod
    def resolve_model_path(path: str, env: str = None) -> str:
        """
        Resolve model path based on environment

        Args:
            path: Original path (may contain environment variables)
            env: Target environment (auto-detect if not specified)

        Returns:
            str: Resolved absolute path

        Example:
            # In WSL environment
            >>> EnvHelper.resolve_model_path("E:/animetta_data/models")
            "/mnt/e/animetta_data/models"

            # In Windows environment
            >>> EnvHelper.resolve_model_path("/mnt/e/animetta_data/models")
            "E:/animetta_data/models"
        """
        if env is None:
            env = EnvHelper.detect_environment()

        # Expand environment variables
        resolved_path = os.path.expandvars(path)

        # Convert path based on target environment
        current_env = EnvHelper.detect_environment()

        if current_env != env:
            logger.info(f"[EnvHelper] Path conversion: {current_env} -> {env}")

            if current_env == Environment.WSL and env == Environment.WINDOWS:
                # WSL -> Windows
                return EnvHelper.convert_wsl_to_windows(resolved_path)
            elif current_env == Environment.WINDOWS and env == Environment.WSL:
                # Windows -> WSL
                return EnvHelper.convert_windows_to_wsl(resolved_path)

        return resolved_path

    @staticmethod
    def get_data_dir() -> Path:
        """
        Get data directory (auto-adapts to environment)

        Priority:
        1. Environment variable ANIMETTA_DATA_DIR
        2. Default location (auto-selected by environment)

        Returns:
            Path: Data directory path
        """
        # 1. Check environment variable
        env_dir = os.getenv("ANIMETTA_DATA_DIR")
        if env_dir:
            return Path(env_dir)

        # 2. Select default location based on environment
        env = EnvHelper.detect_environment()

        if env == Environment.WINDOWS:
            # Windows: E:/animetta_data or user home directory
            if Path("E:/animetta_data").exists():
                return Path("E:/animetta_data")
            return Path.home() / "animetta_data"

        elif env == Environment.WSL:
            # WSL: Try to access Windows E drive
            wsl_path = Path("/mnt/e/animetta_data")
            if wsl_path.exists():
                return wsl_path
            # Otherwise use Linux home directory
            return Path.home() / "animetta_data"

        else:
            # Linux/Mac: user home directory
            return Path.home() / "animetta_data"

    @staticmethod
    def get_default_model_config() -> dict:
        """
        Return the canonical minimal runtime environment template.

        Returns:
            dict: Profile, bind endpoint, and empty provider secrets
        """
        return {
            "ANIMETTA_PROFILE": "test",
            "ANIMETTA_HOST": "127.0.0.1",
            "ANIMETTA_PORT": "12394",
            "DEEPSEEK_API_KEY": "",
            "MIMO_API_KEY": "",
            "QWEN_TTS_API_KEY": "",
        }

    @staticmethod
    def setup_env_file(target_env: str = None, overwrite: bool = False):
        """
        Auto-generate .env file

        Args:
            target_env: Target environment (auto-detect if not specified)
            overwrite: Whether to overwrite existing file

        Returns:
            Path: Generated .env file path
        """
        if target_env is None:
            target_env = EnvHelper.detect_environment()

        project_root = Path(__file__).parent.parent.parent.parent
        env_file = project_root / ".env"

        # Check if file already exists
        if env_file.exists() and not overwrite:
            logger.warning(f"[EnvHelper] .env file already exists: {env_file}")
            logger.warning("[EnvHelper] To overwrite, use overwrite=True")
            return env_file

        # Generate configuration
        config = EnvHelper.get_default_model_config()

        # Add comments
        lines = [
            f"# Auto-generated .env for {target_env.upper()} environment",
            "# Generated by: EnvHelper.setup_env_file()",
            f"# Platform: {platform.system()}",
            "",
        ]

        # Add configuration items
        for key, value in config.items():
            lines.append(f"{key}={value}")

        # Write to file
        env_file.write_text("\n".join(lines) + "\n")
        logger.info(f"[EnvHelper] ✅ .env file generated: {env_file}")
        logger.info("[EnvHelper] Runtime profile template: {}", config["ANIMETTA_PROFILE"])

        return env_file

    @staticmethod
    def print_environment_info():
        """Print current environment info (for debugging)"""
        env = EnvHelper.detect_environment()
        data_dir = EnvHelper.get_data_dir()

        print("=" * 50)
        print("  Animetta Environment Information")
        print("=" * 50)
        print(f"OS: {platform.system()} {platform.release()}")
        print(f"Python Version: {sys.version.split()[0]}")
        print(f"Detected Environment: {env.upper()}")
        print(f"Data Directory: {data_dir}")
        print(f"Directory Exists: {'✅' if data_dir.exists() else '❌'}")
        print(f"Writable: {'✅' if os.access(data_dir, os.W_OK) else '❌'}")
        print("=" * 50)


# Convenience functions
def detect_env() -> str:
    """Detect current environment"""
    return EnvHelper.detect_environment()


def get_data_dir() -> Path:
    """Get data directory"""
    return EnvHelper.get_data_dir()


def resolve_path(path: str) -> str:
    """Resolve path (cross-environment)"""
    return EnvHelper.resolve_model_path(path)


if __name__ == "__main__":
    # Command line test
    import argparse

    parser = argparse.ArgumentParser(description="Animetta 环境工具")
    parser.add_argument("--info", action="store_true", help="显示环境信息")
    parser.add_argument("--setup-env", action="store_true", help="生成 .env 文件")
    parser.add_argument("--convert", metavar="PATH", help="转换路径格式")
    parser.add_argument("--target", choices=["windows", "wsl", "linux"], help="目标环境")

    args = parser.parse_args()

    if args.info:
        EnvHelper.print_environment_info()

    elif args.setup_env:
        EnvHelper.setup_env_file(overwrite=False)

    elif args.convert:
        if not args.target:
            print("❌ 错误: --convert 需要 --target 参数")
            sys.exit(1)
        result = EnvHelper.resolve_model_path(args.convert, args.target)
        print(f"转换结果: {result}")

    else:
        parser.print_help()
