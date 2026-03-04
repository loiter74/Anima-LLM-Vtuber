"""
环境检测和路径映射工具
Environment Detection and Path Mapping Utility

自动检测当前运行环境，并提供跨平台路径转换
"""

import os
import sys
import platform
from pathlib import Path
from loguru import logger


class Environment:
    """环境类型枚举"""
    WINDOWS = "windows"
    WSL = "wsl"
    LINUX = "linux"
    MACOS = "macos"


class EnvHelper:
    """环境辅助工具类"""

    @staticmethod
    def detect_environment() -> str:
        """
        检测当前运行环境

        Returns:
            str: 环境类型 (windows/wsl/linux/macos)
        """
        system = platform.system().lower()

        if system == "windows":
            return Environment.WINDOWS
        elif system == "darwin":
            return Environment.MACOS
        elif system == "linux":
            # 检测是否是 WSL
            return EnvHelper._check_wsl()

        return Environment.LINUX

    @staticmethod
    def _check_wsl() -> str:
        """
        检测是否运行在 WSL 环境中

        Returns:
            str: wsl 或 linux
        """
        try:
            # 方法 1: 检查 /proc/version
            if Path("/proc/version").exists():
                with open("/proc/version", "r") as f:
                    version_info = f.read().lower()
                    if "microsoft" in version_info or "wsl" in version_info:
                        return Environment.WSL
        except Exception:
            pass

        # 方法 2: 检查环境变量
        if os.getenv("WSL_DISTRO_NAME") or os.getenv("WSLENV"):
            return Environment.WSL

        return Environment.LINUX

    @staticmethod
    def convert_windows_to_wsl(windows_path: str) -> str:
        """
        将 Windows 路径转换为 WSL 路径

        Args:
            windows_path: Windows 路径 (如 E:/anima_data)

        Returns:
            str: WSL 路径 (如 /mnt/e/anima_data)

        Example:
            >>> EnvHelper.convert_windows_to_wsl("E:/anima_data/models")
            "/mnt/e/anima_data/models"
        """
        path = Path(windows_path)

        # 处理 Windows 盘符
        if len(path.parts) >= 1 and len(path.parts[0]) == 2 and path.parts[0][1] == ':':
            drive = path.parts[0][0].lower()
            rest = path.as_posix()[3:]  # 去掉 "X:/"
            return f"/mnt/{drive}/{rest}"

        return path.as_posix()

    @staticmethod
    def convert_wsl_to_windows(wsl_path: str) -> str:
        """
        将 WSL 路径转换为 Windows 路径

        Args:
            wsl_path: WSL 路径 (如 /mnt/e/anima_data)

        Returns:
            str: Windows 路径 (如 E:\\anima_data)

        Example:
            >>> EnvHelper.convert_wsl_to_windows("/mnt/e/anima_data/models")
            "E:\\anima_data\\models"
        """
        path = wsl_path

        # 处理 /mnt/X/ 格式
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
        根据环境解析模型路径

        Args:
            path: 原始路径（可能包含环境变量）
            env: 目标环境（不指定则自动检测）

        Returns:
            str: 解析后的绝对路径

        Example:
            # 在 WSL 环境中
            >>> EnvHelper.resolve_model_path("E:/anima_data/models")
            "/mnt/e/anima_data/models"

            # 在 Windows 环境中
            >>> EnvHelper.resolve_model_path("/mnt/e/anima_data/models")
            "E:/anima_data/models"
        """
        if env is None:
            env = EnvHelper.detect_environment()

        # 展开环境变量
        resolved_path = os.path.expandvars(path)

        # 根据目标环境进行路径转换
        current_env = EnvHelper.detect_environment()

        if current_env != env:
            logger.info(f"[EnvHelper] 路径转换: {current_env} -> {env}")

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
        获取数据目录（自动适配环境）

        优先级:
        1. 环境变量 ANIMA_DATA_DIR
        2. 默认位置（根据环境自动选择）

        Returns:
            Path: 数据目录路径
        """
        # 1. 检查环境变量
        env_dir = os.getenv("ANIMA_DATA_DIR")
        if env_dir:
            return Path(env_dir)

        # 2. 根据环境选择默认位置
        env = EnvHelper.detect_environment()

        if env == Environment.WINDOWS:
            # Windows: E:/anima_data 或用户主目录
            if Path("E:/anima_data").exists():
                return Path("E:/anima_data")
            return Path.home() / "anima_data"

        elif env == Environment.WSL:
            # WSL: 尝试访问 Windows E 盘
            wsl_path = Path("/mnt/e/anima_data")
            if wsl_path.exists():
                return wsl_path
            # 否则使用 Linux 主目录
            return Path.home() / "anima_data"

        else:
            # Linux/Mac: 用户主目录
            return Path.home() / "anima_data"

    @staticmethod
    def get_default_model_config() -> dict:
        """
        获取当前环境的默认模型配置

        Returns:
            dict: 模型路径配置
        """
        data_dir = EnvHelper.get_data_dir()

        return {
            "ANIMA_DATA_DIR": str(data_dir),
            "ANIMA_BASE_MODEL_PATH": str(data_dir / "models" / "base_models" / "Qwen1.5-1.8B-Chat"),
            "ANIMA_LORA_PATH": str(data_dir / "models" / "checkpoints" / "neuro-vtuber-v1"),
            "ANIMA_VECTOR_DB_PATH": str(data_dir / "vectordb"),
            "ANIMA_HISTORY_PATH": str(data_dir / "histories"),
        }

    @staticmethod
    def setup_env_file(target_env: str = None, overwrite: bool = False):
        """
        自动生成 .env 文件

        Args:
            target_env: 目标环境 (不指定则自动检测)
            overwrite: 是否覆盖已存在的文件

        Returns:
            Path: 生成的 .env 文件路径
        """
        if target_env is None:
            target_env = EnvHelper.detect_environment()

        project_root = Path(__file__).parent.parent.parent.parent
        env_file = project_root / ".env"

        # 检查是否已存在
        if env_file.exists() and not overwrite:
            logger.warning(f"[EnvHelper] .env 文件已存在: {env_file}")
            logger.warning("[EnvHelper] 如需覆盖，请使用 overwrite=True")
            return env_file

        # 生成配置
        config = EnvHelper.get_default_model_config()

        # 添加注释
        lines = [
            f"# Auto-generated .env for {target_env.upper()} environment",
            f"# Generated by: EnvHelper.setup_env_file()",
            f"# Platform: {platform.system()}",
            f"",
        ]

        # 添加配置项
        for key, value in config.items():
            lines.append(f"{key}={value}")

        # 写入文件
        env_file.write_text("\n".join(lines) + "\n")
        logger.info(f"[EnvHelper] ✅ 已生成 .env 文件: {env_file}")
        logger.info(f"[EnvHelper] 📝 数据目录: {config['ANIMA_DATA_DIR']}")

        return env_file

    @staticmethod
    def print_environment_info():
        """打印当前环境信息（调试用）"""
        env = EnvHelper.detect_environment()
        data_dir = EnvHelper.get_data_dir()

        print("=" * 50)
        print("  Anima 环境信息")
        print("=" * 50)
        print(f"操作系统: {platform.system()} {platform.release()}")
        print(f"Python版本: {sys.version.split()[0]}")
        print(f"检测环境: {env.upper()}")
        print(f"数据目录: {data_dir}")
        print(f"目录存在: {'✅' if data_dir.exists() else '❌'}")
        print(f"可写入: {'✅' if os.access(data_dir, os.W_OK) else '❌'}")
        print("=" * 50)


# 便捷函数
def detect_env() -> str:
    """检测当前环境"""
    return EnvHelper.detect_environment()


def get_data_dir() -> Path:
    """获取数据目录"""
    return EnvHelper.get_data_dir()


def resolve_path(path: str) -> str:
    """解析路径（跨环境）"""
    return EnvHelper.resolve_model_path(path)


if __name__ == "__main__":
    # 命令行测试
    import argparse

    parser = argparse.ArgumentParser(description="Anima 环境工具")
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
