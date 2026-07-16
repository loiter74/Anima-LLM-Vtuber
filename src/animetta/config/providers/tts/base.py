"""TTS base configuration"""

from pydantic import Field

from ...core.base import ProviderConfig
from ...core.mixins import ApiKeyMixin, ModelMixin


class TTSBaseConfig(ProviderConfig, ApiKeyMixin, ModelMixin):
    """
    TTS provider configuration base class

    All TTS provider configurations should inherit from this class
    """

    voice: str = Field(default="default", description="Voice / timbre")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed")
