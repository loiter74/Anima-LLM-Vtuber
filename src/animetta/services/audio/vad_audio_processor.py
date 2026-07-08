from __future__ import annotations

"""
VAD audio processor implementation

VAD-based voice activity detection and audio accumulation
"""

import time
from collections.abc import Callable
from typing import Any

from loguru import logger

from ..vad import VADInterface, VADState
from .processor import AudioProcessorInterface


class VADAudioProcessor(AudioProcessorInterface):
    """
    VAD Audio Processor

    Responsibilities:
    - Receive audio data stream
    - Perform voice activity detection using VAD
    - Accumulate valid speech segments
    - Trigger ASR transcription and LLM conversation
    """

    def __init__(
        self,
        session_id: str,
        vad_engine: VADInterface,
        on_speech_start: Callable | None = None,
        on_speech_end: Callable[[list[float]], Any] | None = None,
        sample_rate: int = 16000,
        vad_timeout_seconds: float = 30.0,
    ):
        """
        Initialize the VAD audio processor

        Args:
            session_id: Session ID
            vad_engine: VAD engine
            on_speech_start: Speech start callback
            on_speech_end: Speech end callback, receives accumulated audio data
            sample_rate: Sample rate
            vad_timeout_seconds: VAD timeout (seconds)
        """
        self.session_id = session_id
        self.vad_engine = vad_engine
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.sample_rate = sample_rate
        self.vad_timeout_seconds = vad_timeout_seconds

        # Audio buffer
        self._audio_buffer: list[float] = []

        # VAD state tracking
        self._vad_active_start_time: float | None = None
        self._vad_chunk_count = 0
        self._is_speaking = False
        self._last_speech_time: float | None = None

        # Statistics
        self._total_chunks = 0
        self._speech_chunks = 0

        # Force timeout mechanism
        self._first_audio_time: float | None = None
        self._max_audio_duration = 30.0  # Maximum audio duration (seconds)

    async def process_chunk(self, audio_data: list[float]) -> None:
        """
        Process audio data chunk

        Args:
            audio_data: Audio data (float32 list)
        """
        if not audio_data:
            return

        self._total_chunks += 1

        # Debug log: output every 500 chunks
        if self._total_chunks % 500 == 0:
            logger.info(f"[{self.session_id}] [AudioProcessor] Audio chunks: {self._total_chunks}")

        # Audio duration progress log: output every 10 seconds
        if self._is_speaking and self._first_audio_time and self._total_chunks % 333 == 0:  # approx 10 seconds
            audio_duration = time.time() - self._first_audio_time
            logger.info(f"[{self.session_id}] [AudioProcessor] Audio duration: {audio_duration:.1f}s / {self._max_audio_duration:.1f}s")

        # If no VAD engine, accumulate directly
        if not self.vad_engine:
            self._audio_buffer.extend(audio_data)
            if self._total_chunks == 1:
                logger.warning(f"[{self.session_id}] No VAD engine, audio will accumulate until manual end")
            return

        # VAD detection
        try:
            result = self.vad_engine.detect_speech(audio_data)
            current_time = time.time()

            # Handle VAD state
            if result.state == VADState.ACTIVE:
                self._handle_vad_active(current_time, audio_data)
            elif result.state == VADState.IDLE:
                self._handle_vad_idle(current_time)

            # Handle VAD events
            if result.is_speech_start:
                await self._handle_speech_start()

            if result.is_speech_end and getattr(result, "speech_detected", True) is False:
                self._discard_unconfirmed_speech()
            elif result.is_speech_end and len(self._audio_buffer) > 1024:
                await self._handle_speech_end()

            # Force timeout check: regardless of VAD state, end if exceeds max duration
            if self._is_speaking and self._first_audio_time:
                audio_duration = time.time() - self._first_audio_time
                if audio_duration > self._max_audio_duration:
                    logger.warning(f"[{self.session_id}] Force timeout ({audio_duration:.1f}s), ending speech")
                    await self._handle_speech_end()

        except Exception as e:
            logger.error(f"[{self.session_id}] VAD error: {e}", exc_info=True)

    async def process_end(self) -> None:
        """Handle audio input end"""
        if not self._audio_buffer:
            logger.warning(f"[{self.session_id}] No audio data to process")
            return

        audio_duration = len(self._audio_buffer) / self.sample_rate
        logger.info(f"[{self.session_id}] Audio end: {audio_duration:.2f}s, {len(self._audio_buffer)} samples")

        # Trigger speech end
        await self._handle_speech_end()

    def reset(self) -> None:
        """Reset processor state"""
        self._audio_buffer.clear()
        self._vad_active_start_time = None
        self._vad_chunk_count = 0
        self._is_speaking = False
        self._last_speech_time = None
        logger.debug(f"[{self.session_id}] Audio processor reset")

    def is_speaking(self) -> bool:
        """Whether speech is currently being detected"""
        return self._is_speaking

    # ========================================
    # Internal methods
    # ========================================

    def _handle_vad_active(self, current_time: float, audio_data: list[float]) -> None:
        """Handle VAD active state"""
        if self._vad_active_start_time is None:
            self._vad_active_start_time = current_time
            self._vad_chunk_count = 0

        # Record first audio time
        if self._first_audio_time is None:
            self._first_audio_time = current_time

        self._vad_chunk_count += 1
        self._last_speech_time = current_time

        # Accumulate audio data
        self._audio_buffer.extend(audio_data)

        # Check timeout
        active_duration = current_time - self._vad_active_start_time
        if active_duration > self.vad_timeout_seconds:
            logger.warning(
                f"[{self.session_id}] VAD active for {active_duration:.1f}s, "
                f"exceeds timeout {self.vad_timeout_seconds}s"
            )
            # Force end
            self._vad_active_start_time = None

    def _handle_vad_idle(self, current_time: float) -> None:
        """Handle VAD idle state"""
        # Check if state needs to be cleared
        if self._vad_active_start_time is not None:
            idle_duration = current_time - self._last_speech_time if self._last_speech_time else 0

            # Exceeds silence threshold, clear VAD active state
            if idle_duration > 2.0:  # Clear after 2 seconds of silence
                self._clear_vad_state()

    def _clear_vad_state(self) -> None:
        """Clear VAD active state"""
        if self._vad_active_start_time is not None:
            logger.debug(f"[{self.session_id}] Clearing VAD active state after {self._vad_chunk_count} chunks")
            self._vad_active_start_time = None
            self._vad_chunk_count = 0

    def _discard_unconfirmed_speech(self) -> None:
        """Discard a locally detected segment that remote VAD/ASR rejected."""
        logger.info(f"[{self.session_id}] Discarding unconfirmed speech segment")
        self._audio_buffer.clear()
        self._is_speaking = False
        self._first_audio_time = None
        self._last_speech_time = None
        self._clear_vad_state()

    async def _handle_speech_start(self) -> None:
        """Handle speech start"""
        if self._is_speaking:
            return

        self._is_speaking = True
        self._speech_chunks += 1

        logger.info(f"[{self.session_id}] 🎤 Speech started (chunk #{self._speech_chunks})")

        if self.on_speech_start:
            try:
                await self.on_speech_start()
            except Exception as e:
                logger.error(f"[{self.session_id}] Error in speech_start callback: {e}")

    async def _handle_speech_end(self, audio_data: list[float] | None = None) -> None:
        """Handle speech end"""
        if not self._is_speaking:
            return

        # Use accumulated audio data
        if audio_data is None:
            audio_data = list(self._audio_buffer)

        audio_duration = len(audio_data) / self.sample_rate

        logger.info(
            f"[{self.session_id}] 🎤 Speech ended: "
            f"{audio_duration:.2f}s, {len(audio_data)} samples, "
            f"{self._total_chunks} total chunks"
        )

        self._is_speaking = False
        self._first_audio_time = None  # Reset first audio time
        self._clear_vad_state()

        # Trigger callback
        if self.on_speech_end:
            try:
                result = await self.on_speech_end(audio_data)
                logger.debug(f"[{self.session_id}] Speech end callback completed")
                return result
            except Exception as e:
                logger.error(f"[{self.session_id}] Error in speech_end callback: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get statistics"""
        return {
            "total_chunks": self._total_chunks,
            "speech_chunks": self._speech_chunks,
            "buffer_size": len(self._audio_buffer),
            "is_speaking": self._is_speaking,
            "buffer_duration": len(self._audio_buffer) / self.sample_rate if self._audio_buffer else 0,
        }
