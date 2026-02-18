"""配置基类模块"""

from typing import ClassVar
from pydantic import BaseModel, Field


class BaseConfig(BaseModel):
    """所有配置的基类"""
    
    class Config:
        extra = "forbid"  # 禁止额外字段
        validate_default = True  # 验证默认值


class ProviderConfig(BaseModel):
    """
    提供者配置基类
    
    所有 LLM/ASR/TTS 提供者配置都应继承此类，
    并定义 type 字段作为鉴别符（用于 Pydantic Discriminated Unions）
    
    示例:
        class OpenAILLMConfig(ProviderConfig):
            type: Literal["openai"] = "openai"
            model: str = "gpt-4o-mini"
    """
    type: str = Field(description="提供者类型，用于鉴别配置类型")
    
    class Config:
        extra = "forbid"
        validate_default = True
    
    @classmethod
    def get_provider_type(cls) -> str:
        """获取提供者类型标识"""
        if "type" in cls.model_fields:
            default = cls.model_fields["type"].default
            if default is not None:
                return str(default)
        return cls.__name__.replace("Config", "").lower()