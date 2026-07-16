"""Mock VC provider configuration"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import VCBaseConfig


@ProviderRegistry.register_config("vc", "mock")
class MockVCConfig(VCBaseConfig):
    """Mock VC configuration - for testing"""

    type: Literal["mock"] = "mock"
