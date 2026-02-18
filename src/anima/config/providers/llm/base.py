"""LLM 配置基类"""

from typing import Optional
from pydantic import Field

from ...core.base import ProviderConfig


class LLMBaseConfig(ProviderConfig):
    """
    LLM 提供者配置基类
    
    所有 LLM 提供者配置都应继承此类
    """
    api_key: Optional[str] = Field(default=None, description="API Key")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度参数")
    max_tokens: int = Field(default=4096, ge=1, description="最大生成 token 数")