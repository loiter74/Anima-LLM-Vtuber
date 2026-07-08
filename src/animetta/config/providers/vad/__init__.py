"""VAD provider configuration — discriminated union for YAML deserialization."""

from ...core.registry import ProviderRegistry

# Import all implementations so their @register_config decorators fire
from .base import VADBaseConfig  # noqa: F401 — triggers registration chain
from .mimo import MimoVADConfig  # noqa: F401
from .mock import MockVADConfig  # noqa: F401
from .silero import SileroVADConfig  # noqa: F401

# Discriminated Union type — auto-generated from registered configs
VADConfig = ProviderRegistry.create_union_type("vad")

__all__ = [
    "VADBaseConfig",
    "VADConfig",
    "MimoVADConfig",
]
