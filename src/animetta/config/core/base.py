"""Base configuration module"""

from pydantic import BaseModel, ConfigDict, Field


class BaseConfig(BaseModel):
    """Base class for all configurations"""

    model_config = ConfigDict(extra="forbid", validate_default=True)


class ProviderConfig(BaseModel):
    """
    Provider configuration base class

    All LLM/ASR/TTS provider configurations should inherit from this class,
    and define the type field as a discriminator (for Pydantic Discriminated Unions)

    Example:
        class OpenAILLMConfig(ProviderConfig):
            type: Literal["openai"] = "openai"
            model: str = "gpt-4o-mini"
    """

    type: str = Field(description="Provider type, used for discriminating configuration types")

    model_config = ConfigDict(extra="forbid", validate_default=True)

    @classmethod
    def get_provider_type(cls) -> str:
        """Get provider type identifier"""
        if "type" in cls.model_fields:
            default = cls.model_fields["type"].default
            if default is not None:
                return str(default)
        return cls.__name__.replace("Config", "").lower()
