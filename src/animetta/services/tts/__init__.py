"""Lazy public exports for TTS service implementations.

Importing one concrete provider must not initialize the factory, tracing, or
other providers.  This is the package boundary used by the standalone Qwen
worker image.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .contrib.chattts_tts import ChatTTSTTS as ChatTTSTTS
    from .contrib.glados_effect import GladosEffectProcessor as GladosEffectProcessor
    from .contrib.glm_tts import GLMTTS as GLMTTS
    from .contrib.kokoro_tts import KokoroTTS as KokoroTTS
    from .contrib.vibe_voice_tts import VibeVoiceTTS as VibeVoiceTTS
    from .dashscope_tts import DashScopeRealtimeTTS as DashScopeRealtimeTTS
    from .edge_tts import EdgeTTS as EdgeTTS
    from .factory import TTSFactory as TTSFactory
    from .failover_tts import FailoverTTS as FailoverTTS
    from .gpt_sovits_tts import GPTSoVITSTTS as GPTSoVITSTTS
    from .interface import TTSInterface as TTSInterface
    from .mimo_tts import MimoTTS as MimoTTS
    from .mock_tts import MockTTS as MockTTS
    from .qwen3_tts import Qwen3TTSTTS as Qwen3TTSTTS
    from .remote_tts import RemoteTTS as RemoteTTS

_EXPORTS = {
    "TTSInterface": (".interface", "TTSInterface"),
    "TTSFactory": (".factory", "TTSFactory"),
    "MockTTS": (".mock_tts", "MockTTS"),
    "EdgeTTS": (".edge_tts", "EdgeTTS"),
    "FailoverTTS": (".failover_tts", "FailoverTTS"),
    "DashScopeRealtimeTTS": (".dashscope_tts", "DashScopeRealtimeTTS"),
    "GPTSoVITSTTS": (".gpt_sovits_tts", "GPTSoVITSTTS"),
    "MimoTTS": (".mimo_tts", "MimoTTS"),
    "RemoteTTS": (".remote_tts", "RemoteTTS"),
    "Qwen3TTSTTS": (".qwen3_tts", "Qwen3TTSTTS"),
    "GLMTTS": (".contrib.glm_tts", "GLMTTS"),
    "ChatTTSTTS": (".contrib.chattts_tts", "ChatTTSTTS"),
    "VibeVoiceTTS": (".contrib.vibe_voice_tts", "VibeVoiceTTS"),
    "KokoroTTS": (".contrib.kokoro_tts", "KokoroTTS"),
    "GladosEffectProcessor": (
        ".contrib.glados_effect",
        "GladosEffectProcessor",
    ),
}
_OPTIONAL_EXPORTS = {
    "Qwen3TTSTTS",
    "GLMTTS",
    "ChatTTSTTS",
    "VibeVoiceTTS",
    "KokoroTTS",
    "GladosEffectProcessor",
}


def __getattr__(name: str) -> Any:
    """Load one provider or factory only when requested."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    try:
        value = getattr(import_module(module_name, __name__), attribute)
    except ModuleNotFoundError as exc:
        if name not in _OPTIONAL_EXPORTS or (exc.name and exc.name.startswith("animetta.")):
            raise
        return None
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy public names to introspection tools."""
    return sorted({*globals(), *_EXPORTS})


__all__ = list(_EXPORTS)
