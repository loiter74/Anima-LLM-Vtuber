"""Mock TTS provider configuration"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "mock")
class MockTTSConfig(TTSBaseConfig):
    """Mock TTS configuration - for testing"""

    type: Literal["mock"] = "mock"
