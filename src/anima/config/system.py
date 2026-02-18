"""系统配置"""

from pydantic import Field
from .core.base import BaseConfig


class SystemConfig(BaseConfig):
    """系统配置"""
    host: str = Field(default="localhost", description="服务器地址")
    port: int = Field(default=12394, description="服务器端口")
    debug: bool = Field(default=False, description="调试模式")
    log_level: str = Field(default="INFO", description="日志级别")