from __future__ import annotations

"""
Simplified VAD processor - directly uses probability values
"""
import time
from collections.abc import Callable

import numpy as np
from loguru import logger

from ..vad import VADInterface, VADState


class SimpleVADProcessor:
    """Simplified VAD processor"""

    def __init__(
        self,
        session_id: str,
        vad_engine: VADInterface,
        on_speech_end: Callable | None = None,
        threshold: float = 0.5,
        min_speech_duration: float = 0.5,
        min_silence_duration: float = 0.8,
        sample_rate: int = 16000,
    ):
        self.session_id = session_id
        self.vad_engine = vad_engine
        self.on_speech_end = on_speech_end
        self.threshold = threshold
        self.min_speech_duration = min_speech_duration
        self.min_silence_duration = min_silence_duration
        self.sample_rate = sample_rate

        # Audio buffer
        self._audio_buffer: list[float] = []

        # State
        self._is_speech = False
        self._speech_start_time = None
        self._silence_start_time = None
        self._silence_transition_count = 0
        self._total_chunks = 0

        # Get raw probability from Silero VAD model
        self._silero_model = None
        model = getattr(vad_engine, "model", None)
        if callable(model):
            self._silero_model = model

    def _get_speech_prob(self, audio_data: list[float]) -> float:
        """Get raw speech probability"""
        if self._silero_model is None:
            return 0.0

        try:
            audio_np = np.array(audio_data, dtype=np.float32)
            try:
                import torch

                # Silero VAD model expects (batch, samples) format.
                chunk = torch.from_numpy(audio_np)
                if chunk.ndim == 1:
                    chunk = chunk.unsqueeze(0)
                with torch.no_grad():
                    result = self._silero_model(chunk, self.sample_rate)
            except ImportError:
                chunk = audio_np.reshape(1, -1) if audio_np.ndim == 1 else audio_np
                result = self._silero_model(chunk, self.sample_rate)

            return float(result.item() if hasattr(result, "item") else result)
        except Exception as e:
            logger.error(f"Error getting speech prob: {e}")
            return 0.0

    async def _process_vad_event_chunk(self, audio_data: list[float]) -> None:
        """Process a chunk using a stateful VADInterface without probability model."""
        try:
            result = self.vad_engine.detect_speech(audio_data)
        except Exception as e:
            logger.error(f"Error detecting speech: {e}")
            return

        current_time = time.time()
        state = getattr(result, "state", None)

        if result.is_speech_start or state == VADState.ACTIVE:
            if not self._is_speech:
                self._is_speech = True
                self._speech_start_time = current_time
                self._silence_start_time = None
                self._silence_transition_count = 0
                logger.info(f"[{self.session_id}] 🎤 Speech started")

            self._silence_start_time = None
            self._audio_buffer.extend(audio_data)
        elif self._is_speech:
            self._audio_buffer.extend(audio_data)

        if result.is_speech_end:
            if getattr(result, "speech_detected", True) is False:
                self._discard_unconfirmed_speech()
                return

            speech_buffer = self._samples_from_vad_result(result)
            if not speech_buffer:
                speech_buffer = list(self._audio_buffer)
            await self._finish_speech(speech_buffer)

    def _samples_from_vad_result(self, result) -> list[float]:
        """Convert byte audio carried by VADResult into float samples."""
        audio_bytes = getattr(result, "audio_data", b"")
        if not audio_bytes:
            return []

        try:
            samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        except ValueError:
            return []
        return (samples / 32768.0).tolist()

    async def _finish_speech(self, speech_buffer: list[float]) -> None:
        """Reset speech state and invoke the speech-end callback once."""
        self._is_speech = False
        self._speech_start_time = None
        self._silence_start_time = None
        self._silence_transition_count = 0
        self._audio_buffer.clear()

        reset = getattr(self.vad_engine, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception as e:
                logger.debug(f"[{self.session_id}] VAD reset skipped: {e}")

        if self.on_speech_end:
            await self.on_speech_end(speech_buffer)

    def _discard_unconfirmed_speech(self) -> None:
        """Reset speech state without invoking callbacks."""
        self._is_speech = False
        self._speech_start_time = None
        self._silence_start_time = None
        self._silence_transition_count = 0
        self._audio_buffer.clear()

        reset = getattr(self.vad_engine, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception as e:
                logger.debug(f"[{self.session_id}] VAD reset skipped: {e}")

    async def process_chunk(self, audio_data: list[float]) -> None:
        """Process audio data chunk"""
        if not audio_data:
            return

        self._total_chunks += 1

        # Output every 500 chunks
        if self._total_chunks % 500 == 0:
            logger.info(f"[{self.session_id}] Audio chunks: {self._total_chunks}")

        if self._silero_model is None and hasattr(self.vad_engine, "detect_speech"):
            await self._process_vad_event_chunk(audio_data)
            return

        # Get speech probability
        prob = self._get_speech_prob(audio_data)
        is_speech_frame = prob > self.threshold

        current_time = time.time()

        # Accumulate audio
        self._audio_buffer.extend(audio_data)

        if is_speech_frame:
            # Speech detected
            if not self._is_speech:
                self._is_speech = True
                self._speech_start_time = current_time
                self._silence_start_time = None
                self._silence_transition_count = 0
                logger.info(f"[{self.session_id}] 🎤 Speech started")

            self._silence_start_time = None
        else:
            # Silence detected
            if self._is_speech:
                if self._silence_start_time is None:
                    self._silence_start_time = current_time
                    self._silence_transition_count += 1

                silence_duration = current_time - self._silence_start_time
                speech_duration = current_time - self._speech_start_time if self._speech_start_time else 0

                # Conditions: speech long enough + silence long enough
                if speech_duration >= self.min_speech_duration and silence_duration >= self.min_silence_duration:
                    # Reset state BEFORE callback to prevent duplicate triggers
                    # (next chunk must not see _is_speech=True while callback is awaited)
                    self._is_speech = False
                    self._speech_start_time = None
                    self._silence_start_time = None
                    speech_buffer = list(self._audio_buffer)
                    self._audio_buffer.clear()

                    logger.info(
                        f"[{self.session_id}] 🎤 Speech ended: "
                        f"speech={speech_duration:.2f}s, silence={silence_duration:.2f}s, prob={prob:.3f}"
                    )

                    await self._finish_speech(speech_buffer)
                elif (
                    self._silence_transition_count >= 3
                    and speech_duration <= self.min_speech_duration
                ):
                    # Treat rapid alternating speech/silence as VAD jitter, not an utterance.
                    self._is_speech = False
                    self._speech_start_time = None
                    self._silence_start_time = None
                    self._silence_transition_count = 0

    async def process_end(self) -> None:
        """Manual end"""
        if self._is_speech and self._audio_buffer:
            speech_buffer = list(self._audio_buffer)

            logger.info(f"[{self.session_id}] Manual end of speech input")

            await self._finish_speech(speech_buffer)

    def reset(self) -> None:
        """Reset"""
        self._audio_buffer.clear()
        self._is_speech = False
        self._speech_start_time = None
        self._silence_start_time = None
        self._silence_transition_count = 0
