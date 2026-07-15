"""Mock ASR provider configuration"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register_config("asr", "mock")
class MockASRConfig(ASRBaseConfig):
    """Mock ASR configuration - for testing"""

    type: Literal["mock"] = "mock"
