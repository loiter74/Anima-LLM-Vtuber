"""
User settings management
Manages user personal configuration (not committed to git)
"""

from pathlib import Path

import yaml
from loguru import logger


class UserSettings:
    """User settings management"""

    def __init__(self, root_dir: Path):
        self.config_file = root_dir / ".user_settings.yaml"
        self.settings = self._load()

    def _load(self) -> dict:
        """Load user configuration"""
        if not self.config_file.exists():
            return self._create_default()

        try:
            with open(self.config_file, encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load user configuration: {e}")
            return self._create_default()

    def _create_default(self) -> dict:
        """Create default configuration"""
        return {
            "log_level": "INFO"
        }

    def save(self):
        """Save user configuration"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(self.settings, f, allow_unicode=True)
        except Exception as e:
            logger.error(f"Failed to save user configuration: {e}")

    def get_log_level(self) -> str:
        return self.settings.get("log_level", "INFO")

    def set_log_level(self, level: str):
        self.settings["log_level"] = level
        self.save()
