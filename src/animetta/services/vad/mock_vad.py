from __future__ import annotations

"""
Mock VAD implementation (for testing)
"""


import numpy as np
from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.vad.mock import MockVADConfig

from .interface import VADInterface, VADResult, VADState


@ProviderRegistry.register_service("vad", "mock")
class MockVAD(VADInterface):
    """
    Mock VAD implementation

    Simple volume-based voice activity detection for testing
    No additional dependencies required
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        db_threshold: float = -30.0,
        min_speech_duration: int = 5,
        min_silence_duration: int = 15,
    ):
        self.sample_rate = sample_rate
        self.db_threshold = db_threshold
        self.min_speech_duration = min_speech_duration
        self.min_silence_duration = min_silence_duration

        # State
        self.state = VADState.IDLE
        self.speech_frames = 0
        self.silence_frames = 0

        # Accumulated audio
        self.audio_buffer = bytearray()

        # Pre-buffer
        self.pre_buffer: list[bytes] = []
        self.pre_buffer_max = 10

        logger.info(f"Mock VAD initialized: db_threshold={db_threshold}")

    @classmethod
    def from_config(cls, config: MockVADConfig, **kwargs) -> MockVAD:
        """Create MockVAD from provider config."""
        return cls(
            sample_rate=getattr(config, "sample_rate", 16000),
            db_threshold=getattr(config, "db_threshold", -30.0),
            min_speech_duration=getattr(config, "min_speech_duration", 5),
            min_silence_duration=getattr(config, "min_silence_duration", 15),
        )

    def _calculate_db(self, audio_data: np.ndarray) -> float:
        """Calculate audio decibel value"""
        rms = np.sqrt(np.mean(np.square(audio_data)))
        return 20 * np.log10(rms + 1e-7) if rms > 0 else -np.inf

    def detect_speech(self, audio_data: list | np.ndarray) -> VADResult:
        """
        Detect voice activity in audio data

        Based on simple volume threshold judgment
        """
        # Convert to numpy array
        audio_np = np.array(audio_data, dtype=np.float32)

        # Check if int16 PCM data (value range exceeds [-1.0, 1.0])
        if len(audio_np) > 0 and np.max(np.abs(audio_np)) > 1.0:
            # int16 PCM data, normalize to [-1.0, 1.0]
            audio_np = audio_np / 32767.0

        # Calculate decibel value
        db = self._calculate_db(audio_np)
        is_loud = db > self.db_threshold

        # Convert to bytes
        int_audio = (audio_np * 32767).astype(np.int16)
        chunk_bytes = int_audio.tobytes()

        # State machine
        if self.state == VADState.IDLE:
            # Pre-buffer
            self.pre_buffer.append(chunk_bytes)
            if len(self.pre_buffer) > self.pre_buffer_max:
                self.pre_buffer.pop(0)

            if is_loud:
                self.speech_frames += 1
                if self.speech_frames >= self.min_speech_duration:
                    self.state = VADState.ACTIVE
                    self.speech_frames = 0
                    self.silence_frames = 0
                    self.audio_buffer.extend(chunk_bytes)

                    return VADResult(
                        audio_data=b"",
                        is_speech_start=True,
                        is_speech_end=False,
                        state=VADState.ACTIVE,
                    )
            else:
                self.speech_frames = 0

        elif self.state == VADState.ACTIVE:
            self.audio_buffer.extend(chunk_bytes)

            if is_loud:
                self.silence_frames = 0
            else:
                self.silence_frames += 1
                if self.silence_frames >= self.min_silence_duration:
                    self.state = VADState.IDLE
                    self.silence_frames = 0
                    self.speech_frames = 0

                    # Merge pre-buffer and main buffer
                    pre_bytes = b"".join(self.pre_buffer)
                    completed_audio = pre_bytes + bytes(self.audio_buffer)

                    self.audio_buffer.clear()
                    self.pre_buffer.clear()

                    return VADResult(
                        audio_data=completed_audio,
                        is_speech_start=False,
                        is_speech_end=True,
                        state=VADState.IDLE,
                    )

        return VADResult(
            audio_data=b"", is_speech_start=False, is_speech_end=False, state=self.state
        )

    def reset(self) -> None:
        """Reset state"""
        self.state = VADState.IDLE
        self.speech_frames = 0
        self.silence_frames = 0
        self.audio_buffer.clear()
        self.pre_buffer.clear()
        logger.debug("Mock VAD has been reset")

    def get_current_state(self) -> VADState:
        """Get current state"""
        return self.state

    async def close(self) -> None:
        """Clean up resources"""
        self.reset()
        logger.info("Mock VAD resources released")
