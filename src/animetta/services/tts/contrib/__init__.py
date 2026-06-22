"""Contrib TTS implementations — maintained but not in core CI path.

These implementations are maintained but have external dependencies or
are experimental. They are excluded from the mandatory CI test suite
(mark tests with @pytest.mark.contrib).

Quarterly review: implementations unused for 2 consecutive quarters
should be archived.
"""

from .chattts_tts import ChatTTSTTS
from .glados_effect import GladosEffectProcessor
from .glm_tts import GLMTTS
from .kokoro_tts import KokoroTTS
from .vibe_voice_tts import VibeVoiceTTS

__all__ = [
    "ChatTTSTTS",
    "GLMTTS",
    "KokoroTTS",
    "VibeVoiceTTS",
    "GladosEffectProcessor",
]
