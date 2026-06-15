"""VC (Voice Conversion) provider configuration — discriminated union for YAML deserialization."""

from ...core.registry import ProviderRegistry

# Import all implementations so their @register_config decorators fire
from .base import VCBaseConfig  # noqa: F401 — triggers registration chain
from .mock import MockVCConfig  # noqa: F401
from .rvc import RVCConfig  # noqa: F401

# Discriminated Union type — auto-generated from registered configs
VCConfig = ProviderRegistry.create_union_type("vc")

__all__ = [
    "VCBaseConfig",
    "VCConfig",
]
