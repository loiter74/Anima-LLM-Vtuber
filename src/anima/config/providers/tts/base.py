"""TTS 配置基类"""

from typing import Optional
from pydantic import Field

from ...core.base import ProviderConfig


class TTSBaseConfig(ProviderConfig):
    """
    TTS 提供者配置基类
    
    所有 TTS 提供者配置都应继承此类
    """
    voice: str = Field(default="default", description="声音/音色")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速")
    api_key: Optional[str] = Field(default=None, description="API Key")