"""Audio Source Separation provider configuration — discriminated union for YAML deserialization."""

from ...core.registry import ProviderRegistry

# Import all implementations so their @register_config decorators fire
from .base import SeparationBaseConfig  # noqa: F401 — triggers registration chain
from .demucs import DemucsSeparationConfig  # noqa: F401
from .mock import MockSeparationConfig  # noqa: F401

# Discriminated Union type — auto-generated from registered configs
SeparationConfig = ProviderRegistry.create_union_type("separation")

__all__ = [
    "SeparationBaseConfig",
    "SeparationConfig",
]
