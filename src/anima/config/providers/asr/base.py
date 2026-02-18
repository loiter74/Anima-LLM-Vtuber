"""ASR 配置基类"""

from typing import Optional
from pydantic import Field

from ...core.base import ProviderConfig


class ASRBaseConfig(ProviderConfig):
    """
    ASR 提供者配置基类
    
    所有 ASR 提供者配置都应继承此类
    """
    language: str = Field(default="zh", description="识别语言")
    api_key: Optional[str] = Field(default=None, description="API Key")