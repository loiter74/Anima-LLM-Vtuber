from __future__ import annotations

"""
VAD (Voice Activity Detection) interface definition
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

import numpy as np


class VADState(Enum):
    """VAD state enumeration"""

    IDLE = 1  # Idle state, waiting for speech
    ACTIVE = 2  # Speech detected
    INACTIVE = 3  # Speech ended (silence state)


class VADResult:
    """VAD detection result"""

    def __init__(
        self,
        audio_data: bytes = b"",
        is_speech_start: bool = False,
        is_speech_end: bool = False,
        state: VADState = VADState.IDLE,
        speech_detected: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.audio_data = audio_data
        self.is_speech_start = is_speech_start
        self.is_speech_end = is_speech_end
        self.state = state
        self.speech_detected = speech_detected
        self.metadata = metadata or {}

    @property
    def is_special_signal(self) -> bool:
        """Whether it is a special signal (start/end marker)"""
        return self.is_speech_start or self.is_speech_end

    def __repr__(self):
        if self.is_speech_start:
            return "<VADResult: SPEECH_START>"
        elif self.is_speech_end:
            return f"<VADResult: SPEECH_END, audio_len={len(self.audio_data)}>"
        else:
            return f"<VADResult: state={self.state.name}, audio_len={len(self.audio_data)}>"


class VADInterface(ABC):
    """
    Abstract base class for Voice Activity Detection interface
    All VAD implementations must inherit from this class and implement its abstract methods
    """

    @abstractmethod
    def detect_speech(self, audio_data: list | np.ndarray) -> VADResult:
        """
        Detect voice activity in audio data

        Args:
            audio_data: Audio data (float32 list or numpy array)

        Returns:
            VADResult: Detection result
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset VAD state machine"""
        pass

    @abstractmethod
    def get_current_state(self) -> VADState:
        """Get current state"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources"""
        pass
