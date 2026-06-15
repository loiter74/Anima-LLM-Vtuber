"""
VAD (Voice Activity Detection) module
"""

from .detector import SileroDetector
from .factory import VADFactory
from .interface import VADInterface, VADResult, VADState

# Import implementations to trigger ProviderRegistry registration
try:
    from .mock_vad import MockVAD
    from .silero_vad import SileroStateMachine, SileroVAD
except ImportError:
    SileroVAD = None  # type: ignore
    SileroStateMachine = None  # type: ignore
    MockVAD = None  # type: ignore

__all__ = [
    "VADInterface",
    "VADState",
    "VADResult",
    "VADFactory",
    "SileroDetector",
    "SileroVAD",
    "SileroStateMachine",
    "MockVAD",
]
