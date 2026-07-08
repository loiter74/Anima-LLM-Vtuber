"""TTS service implementation module

Structure:
- Core implementations (active, minimal deps): edge_tts, qwen3_tts, gpt_sovits_tts, mock_tts
- Contrib implementations (maintained/experimental): see contrib/ subpackage

Heavy providers (kokoro, chattts, vibe_voice, glm) are guarded with try/except
so that the module can be imported without their dependencies (torch, etc.)
in lightweight/core deployments.
"""

from .edge_tts import EdgeTTS
from .factory import TTSFactory
from .gpt_sovits_tts import GPTSoVITSTTS
from .interface import TTSInterface
from .mimo_tts import MimoTTS

# Core implementations (lightweight dependencies)
from .mock_tts import MockTTS

# Qwen3 TTS requires torch — guard the import
try:
    from .qwen3_tts import Qwen3TTSTTS
except ImportError:
    Qwen3TTSTTS = None  # type: ignore[assignment,misc]

# Contrib implementations — each guarded individually
try:
    from .contrib import (
        GLMTTS,
        ChatTTSTTS,
        GladosEffectProcessor,
        KokoroTTS,
        VibeVoiceTTS,
    )
except ImportError:
    GLMTTS = None  # type: ignore[assignment,misc]
    ChatTTSTTS = None  # type: ignore[assignment,misc]
    GladosEffectProcessor = None  # type: ignore[assignment,misc]
    KokoroTTS = None  # type: ignore[assignment,misc]
    VibeVoiceTTS = None  # type: ignore[assignment,misc]

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
