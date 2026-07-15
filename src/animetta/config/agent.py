"""Agent configuration"""

from pydantic import Field

from .core.base import BaseConfig
from .providers.llm import GLMLLMConfig, LLMConfig


class AgentConfig(BaseConfig):
    """Agent configuration - combines LLM provider and behavior settings"""

    llm_config: LLMConfig = Field(default_factory=GLMLLMConfig)
    system_prompt: str = Field(default="你是一个友好的 AI 助手。", description="System prompt")
    memory_enabled: bool = Field(default=True, description="Whether to enable memory")
