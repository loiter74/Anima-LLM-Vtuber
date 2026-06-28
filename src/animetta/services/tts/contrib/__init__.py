"""Contrib TTS implementations — maintained but not in core CI path.

These implementations are maintained but have external dependencies or
are experimental. They are excluded from the mandatory CI test suite
(mark tests with @pytest.mark.contrib).

Quarterly review: implementations unused for 2 consecutive quarters
should be archived.

Each import is guarded so lightweight/core deployments can skip heavy
dependencies (torch, kokoro, etc.) without crashing.
"""

try:
    from .chattts_tts import ChatTTSTTS
except ImportError:
    ChatTTSTTS = None  # type: ignore[assignment,misc]

try:
    from .glados_effect import GladosEffectProcessor
except ImportError:
    GladosEffectProcessor = None  # type: ignore[assignment,misc]

try:
    from .glm_tts import GLMTTS
except ImportError:
    GLMTTS = None  # type: ignore[assignment,misc]

try:
    from .kokoro_tts import KokoroTTS
except ImportError:
    KokoroTTS = None  # type: ignore[assignment,misc]

try:
    from .vibe_voice_tts import VibeVoiceTTS
except ImportError:
    VibeVoiceTTS = None  # type: ignore[assignment,misc]

__all__ = [
    "ChatTTSTTS",
    "GLMTTS",
    "KokoroTTS",
    "VibeVoiceTTS",
    "GladosEffectProcessor",
]
