"""TTS provider configuration — discriminated union for YAML deserialization."""

from ...core.registry import ProviderRegistry

# Import all implementations so their @register_config decorators fire
from .base import TTSBaseConfig  # noqa: F401 — triggers registration chain
from .chattts import ChatTTSConfig  # noqa: F401
from .dashscope import DashScopeTTSConfig  # noqa: F401
from .edge import EdgeTTSConfig  # noqa: F401
from .failover import FailoverTTSConfig  # noqa: F401
from .glm import GLMTTSConfig  # noqa: F401
from .gpt_sovits import GPTSoVITSConfig  # noqa: F401
from .kokoro import KokoroTTSConfig  # noqa: F401
from .mimo import MimoTTSConfig  # noqa: F401
from .mock import MockTTSConfig  # noqa: F401
from .openai import OpenAITTSConfig  # noqa: F401
from .qwen3 import Qwen3TTSConfig  # noqa: F401
from .remote import RemoteTTSConfig  # noqa: F401
from .vibe_voice import VibeVoiceTTSConfig  # noqa: F401

# Discriminated Union type — auto-generated from registered configs
TTSConfig = ProviderRegistry.create_union_type("tts")

__all__ = [
    "TTSBaseConfig",
    "TTSConfig",
    "DashScopeTTSConfig",
    "FailoverTTSConfig",
    "MimoTTSConfig",
    "RemoteTTSConfig",
]
