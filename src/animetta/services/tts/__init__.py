"""TTS service implementation module

Structure:
- Core implementations (active, minimal deps): edge_tts, qwen3_tts, gpt_sovits_tts, mock_tts
- Contrib implementations (maintained/experimental): see contrib/ subpackage

Heavy providers (kokoro, chattts, vibe_voice, glm) are guarded with try/except
so that the module can be imported without their dependencies (torch, etc.)
in lightweight/core deployments.
"""

from importlib import import_module

from .edge_tts import EdgeTTS
from .factory import TTSFactory
from .gpt_sovits_tts import GPTSoVITSTTS
from .interface import TTSInterface
from .mimo_tts import MimoTTS

# Core implementations (lightweight dependencies)
from .mock_tts import MockTTS

_LAZY_PROVIDERS = {
    "Qwen3TTSTTS": (".qwen3_tts", "Qwen3TTSTTS"),
    "GLMTTS": (".contrib.glm_tts", "GLMTTS"),
    "ChatTTSTTS": (".contrib.chattts_tts", "ChatTTSTTS"),
    "GladosEffectProcessor": (".contrib.glados_effect", "GladosEffectProcessor"),
    "KokoroTTS": (".contrib.kokoro_tts", "KokoroTTS"),
    "VibeVoiceTTS": (".contrib.vibe_voice_tts", "VibeVoiceTTS"),
}


def __getattr__(name: str):
    """Import optional provider implementations only when requested."""
    target = _LAZY_PROVIDERS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    try:
        value = getattr(import_module(module_name, __name__), attribute)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("animetta."):
            raise
        return None
    globals()[name] = value
    return value

__all__ = [
    "TTSInterface",
    "TTSFactory",
    # Core (always available)
    "MockTTS",
    "EdgeTTS",
    "GPTSoVITSTTS",
    "MimoTTS",
    # Optional (may be None if deps missing)
    "Qwen3TTSTTS",
    "GLMTTS",
    "ChatTTSTTS",
    "VibeVoiceTTS",
    "KokoroTTS",
    "GladosEffectProcessor",
]
