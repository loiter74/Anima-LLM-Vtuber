"""
Loguru 日志管理器
支持动态级别切换
"""

from loguru import logger
import sys
from typing import Optional


class LoggerManager:
    """Loguru 日志管理器，支持动态级别切换"""

    _instance: Optional["LoggerManager"] = None

    def __init__(self):
        self._handler_id = None
        self._current_level = "INFO"
        self._setup_handler()

    @classmethod
    def get_instance(cls) -> "LoggerManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _setup_handler(self, level: str = "INFO"):
        """设置日志 handler"""
        logger.remove()
        self._handler_id = logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level=level,
            colorize=True,
        )
        self._current_level = level

    def set_level(self, level: str) -> bool:
        """动态设置日志级别"""
        level = level.upper()
        valid_levels = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        if level not in valid_levels:
            logger.warning(f"无效的日志级别: {level}")
            return False

        self._setup_handler(level)
        logger.info(f"日志级别已更新为: {level}")
        return True

    def get_level(self) -> str:
        return self._current_level


# 全局单例
logger_manager = LoggerManager.get_instance()
