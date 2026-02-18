"""Agent 配置"""

from pydantic import Field
from .core.base import BaseConfig
from .providers.llm import LLMConfig, GLMLLMConfig


class AgentConfig(BaseConfig):
    """Agent 配置 - 组合 LLM 提供者和行为设置"""
    llm_config: LLMConfig = Field(default_factory=GLMLLMConfig)
    system_prompt: str = Field(
        default="你是一个友好的 AI 助手。",
        description="系统提示词"
    )
    memory_enabled: bool = Field(default=True, description="是否启用记忆")
