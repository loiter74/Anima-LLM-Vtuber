"""TTS service implementation module

Structure:
- Core implementations (active, minimal deps): edge_tts, qwen3_tts, gpt_sovits_tts, mock_tts
- Contrib implementations (maintained/experimental): see contrib/ subpackage
"""

# Contrib implementations (maintained separately)
from .contrib import (
    GLMTTS,
    ChatTTSTTS,
    GladosEffectProcessor,
    KokoroTTS,
    VibeVoiceTTS,
)
from .edge_tts import EdgeTTS
from .factory import TTSFactory
from .gpt_sovits_tts import GPTSoVITSTTS
from .interface import TTSInterface

# Core implementations
from .mock_tts import MockTTS
from .qwen3_tts import Qwen3TTSTTS

__all__ = [
    "TTSInterface",
    "TTSFactory",
    # Core
    "MockTTS",
    "EdgeTTS",
    "GPTSoVITSTTS",
    "Qwen3TTSTTS",
    # Contrib
    "GLMTTS",
    "ChatTTSTTS",
    "VibeVoiceTTS",
    "KokoroTTS",
    "GladosEffectProcessor",
]
