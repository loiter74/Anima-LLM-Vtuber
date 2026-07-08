"""ASR service implementation module

Heavy providers (faster_whisper, funasr) are guarded with try/except
so that the module can be imported without their dependencies
in lightweight/core deployments.
"""

from .factory import ASRFactory
from .glm_asr import GLMASR
from .interface import ASRInterface
from .mimo_asr import MimoASR

# Core implementations (lightweight dependencies)
from .mock_asr import MockASR

# Heavy providers — guarded for core deployments
try:
    from .faster_whisper_asr import FasterWhisperASR
except ImportError:
    FasterWhisperASR = None  # type: ignore[assignment,misc]

try:
    from .funasr_asr import FunASRASR
except ImportError:
    FunASRASR = None  # type: ignore[assignment,misc]

__all__ = [
    "ASRInterface",
    "ASRFactory",
    # Core (always available)
    "MockASR",
    "GLMASR",
    "MimoASR",
    # Optional (may be None if deps missing)
    "FasterWhisperASR",
    "FunASRASR",
]
