"""
用户配置管理
管理用户个人配置（不提交到git）
"""

import yaml
from pathlib import Path
from loguru import logger


class UserSettings:
    """用户配置管理"""

    def __init__(self, root_dir: Path):
        self.config_file = root_dir / ".user_settings.yaml"
        self.settings = self._load()

    def _load(self) -> dict:
        """加载用户配置"""
        if not self.config_file.exists():
            return self._create_default()

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载用户配置失败: {e}")
            return self._create_default()

    def _create_default(self) -> dict:
        """创建默认配置"""
        return {
            "log_level": "INFO"
        }

    def save(self):
        """保存用户配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(self.settings, f, allow_unicode=True)
        except Exception as e:
            logger.error(f"保存用户配置失败: {e}")

    def get_log_level(self) -> str:
        return self.settings.get("log_level", "INFO")

    def set_log_level(self, level: str):
        self.settings["log_level"] = level
        self.save()
