"""ASR provider configuration — discriminated union for YAML deserialization."""

from ...core.registry import ProviderRegistry

# Import all implementations so their @register_config decorators fire
from .base import ASRBaseConfig  # noqa: F401 — triggers registration chain
from .faster_whisper import FasterWhisperASRConfig  # noqa: F401
from .funasr import FunASRConfig  # noqa: F401
from .glm import GLMASRConfig  # noqa: F401
from .mock import MockASRConfig  # noqa: F401
from .openai import OpenAIASRConfig  # noqa: F401

# Discriminated Union type — auto-generated from registered configs
ASRConfig = ProviderRegistry.create_union_type("asr")

__all__ = [
    "ASRBaseConfig",
    "ASRConfig",
]
