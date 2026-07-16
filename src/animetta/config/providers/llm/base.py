"""LLM base configuration"""

from ...core.base import ProviderConfig
from ...core.mixins import ApiKeyMixin, ModelMixin, TemperatureMixin


class LLMBaseConfig(ProviderConfig, ApiKeyMixin, ModelMixin, TemperatureMixin):
    """
    LLM provider configuration base class

    All LLM provider configurations should inherit from this class
    """
