from __future__ import annotations

"""
Silero VAD detector — handles model loading and speech probability detection.

Extracted from silero_vad.py to separate model/detection concerns from
audio processing + state machine logic.
"""

import numpy as np
from loguru import logger

from .interface import VADResult, VADState


class SileroDetector:
    """
    Handles Silero VAD model loading and speech probability detection.

    This class encapsulates:
    - Model loading (_load_vad_model)
    - Speech probability calculation (get_speech_prob)
    - Audio preprocessing and chunk-based detection (detect)

    The state machine (SileroStateMachine) is owned by SileroVAD and
    passed in during detection.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

        # Window size: 512 samples at 16kHz (approx 32ms)
        self.window_size_samples = 512 if sample_rate == 16000 else 256

        # Load model
        self.model = self._load_vad_model()

        # Diagnostic log flags (prevent duplicate logs)
        self._vad_logged = False
        self._vad_int16_logged = False
        self._vad_normalized_logged = False

    def _load_vad_model(self):
        """Load Silero VAD model"""
        try:
            from silero_vad import load_silero_vad
            logger.info("Loading Silero-VAD model...")
            model = load_silero_vad()
            logger.info("Silero-VAD model loaded successfully")
            return model
        except ImportError:
            logger.warning("silero-vad is not installed, please run: pip install silero-vad")
            raise
        except Exception as e:
            logger.error(f"Failed to load Silero-VAD model: {e}")
            raise

    def get_speech_prob(self, audio_chunk: np.ndarray) -> float:
        """
        Calculate speech probability for a single audio chunk.

        Args:
            audio_chunk: float32 numpy array (window_size_samples length)

        Returns:
            float: Speech probability (0.0 to 1.0)
        """
        try:
            import torch
        except ImportError:
            result = self.model(audio_chunk, self.sample_rate)
        else:
            chunk_tensor = torch.Tensor(audio_chunk)
            with torch.no_grad():
                result = self.model(chunk_tensor, self.sample_rate)

        if hasattr(result, "item"):
            result = result.item()
        return float(result)

    def detect(self, audio_data: list | np.ndarray, vad_instance) -> VADResult:
        """
        Detect voice activity in audio data.

        Processing flow:
        1. Split audio into chunks (512 samples each)
        2. Calculate speech probability for each chunk
        3. Use state machine to determine speech start/end

        Args:
            audio_data: Audio data (float32 list or numpy array, range [-1.0, 1.0] or int16 PCM)
            vad_instance: SileroVAD instance (for config params and state machine)

        Returns:
            VADResult: Detection result
        """
        # Convert to numpy array with smart normalization
        audio_np = np.array(audio_data, dtype=np.float32)

        # Diagnostic: record original audio data range (only first chunk, avoid flooding)
        if not self._vad_logged:
            if len(audio_np) > 0:
                float(np.min(audio_np))
                float(np.max(audio_np))
                float(np.max(np.abs(audio_np)))
            self._vad_logged = True
        elif len(audio_np) > 0:
            float(np.min(audio_np))
            float(np.max(audio_np))
            float(np.max(np.abs(audio_np)))
        else:
            pass

        # Check if int16 PCM data (value range exceeds [-1.0, 1.0])
        if len(audio_np) > 0 and np.max(np.abs(audio_np)) > 1.0:
            # int16 PCM data, normalize to [-1.0, 1.0]
            if not self._vad_int16_logged:
                logger.info("[VAD] ✅ Detected int16 PCM data format, will auto-normalize")
                self._vad_int16_logged = True
            audio_np = audio_np / 32767.0

        # Print normalized signal amplitude (only once)
        if not self._vad_normalized_logged:
            norm_min = float(np.min(audio_np)) if len(audio_np) > 0 else 0
            norm_max = float(np.max(audio_np)) if len(audio_np) > 0 else 0
            norm_rms = float(np.sqrt(np.mean(audio_np**2))) if len(audio_np) > 0 else 0
            logger.info(f"[VAD] 📊 Normalized signal range: [{norm_min:.4f}, {norm_max:.4f}], RMS: {norm_rms:.4f}")
            logger.info(f"[VAD] 💡 Tip: Silero VAD works well when RMS > 0.01, current RMS: {norm_rms:.4f}")
            self._vad_normalized_logged = True

        # Critical fix: record all events, return the last important event
        # Do not return on first event, process all chunks
        speech_start_event = None
        speech_end_event = None

        # Chunk processing
        for i in range(0, len(audio_np), self.window_size_samples):
            chunk_np = audio_np[i: i + self.window_size_samples]

            # Fix: do not skip incomplete chunks, process them too
            if len(chunk_np) < self.window_size_samples:
                # Last chunk may be incomplete, pad with zeros
                padded_chunk = np.zeros(self.window_size_samples, dtype=np.float32)
                padded_chunk[:len(chunk_np)] = chunk_np
                chunk_np = padded_chunk

            # Calculate speech probability
            speech_prob = self.get_speech_prob(chunk_np)

            # Process through state machine
            result = vad_instance.state_machine.process(speech_prob, chunk_np)

            # Record events without immediately returning
            if result is not None:
                if result.is_speech_start:
                    speech_start_event = result
                elif result.is_speech_end:
                    speech_end_event = result

        # Return highest priority event: speech_end > speech_start > normal state
        if speech_end_event is not None:
            # Only log at DEBUG level to avoid flooding
            logger.debug(f"[VAD] Speech ended, audio length: {len(speech_end_event.audio_data)} bytes")
            return speech_end_event
        elif speech_start_event is not None:
            return speech_start_event

        # No special events, return current state
        return VADResult(
            audio_data=b"",
            is_speech_start=False,
            is_speech_end=False,
            state=vad_instance.state_machine.state
        )

    def get_current_state(self, vad_instance) -> VADState:
        """Get current VAD state from the state machine."""
        return vad_instance.state_machine.state
