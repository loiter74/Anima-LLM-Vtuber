"""OpenAI ASR 提供者配置"""

from typing import Optional, Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register("asr", "openai")
class OpenAIASRConfig(ASRBaseConfig):
    """OpenAI ASR (Whisper) 配置"""
    type: Literal["openai"] = "openai"
    model: str = Field(default="whisper-1", description="Whisper 模型名称")
    base_url: Optional[str] = Field(default=None, description="API Base URL")