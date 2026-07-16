"""Mock Separation provider configuration"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import SeparationBaseConfig


@ProviderRegistry.register_config("separation", "mock")
class MockSeparationConfig(SeparationBaseConfig):
    """Mock Separation configuration - for testing"""

    type: Literal["mock"] = "mock"
