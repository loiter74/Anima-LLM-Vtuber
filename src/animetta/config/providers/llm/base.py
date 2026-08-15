"""LLM base configuration"""

from pydantic import Field

from ...core.base import ProviderConfig
from ...core.mixins import ApiKeyMixin, ModelMixin, TemperatureMixin
from .pricing import ModelPricingV1


class LLMBaseConfig(ProviderConfig, ApiKeyMixin, ModelMixin, TemperatureMixin):
    """
    LLM provider configuration base class

    All LLM provider configurations should inherit from this class
    """

    pricing: ModelPricingV1 | None = Field(default=None)
