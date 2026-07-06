from __future__ import annotations

"""
Kokoro TTS implementation - open-weight multilingual TTS model.

Kokoro is an 82M parameter StyleTTS2-based model supporting
Chinese (Mandarin) and English with high-quality output.

https://github.com/hexgrad/kokoro
"""

# Status: maintained
# Last verified: 2026-05-23
import io
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.utils.tempfiles import write_temp_bytes

from ..interface import TTSInterface
from .glados_effect import KOKORO_SAMPLE_RATE, GladosEffectProcessor


@ProviderRegistry.register_service("tts", "kokoro")
class KokoroTTS(TTSInterface):
    """
    Kokoro TTS implementation using the Kokoro-82M model.

    Supports Chinese (Mandarin) and English with multiple voice options.
    Optionally applies GLaDOS-style electronic voice effects.

    The model is loaded lazily on first synthesize() call to avoid
    blocking initialization. Model weights are auto-downloaded from
    HuggingFace on first use and cached locally.
    """

    def __init__(
        self,
        voice: str = "zf_xiaobei",
        model_repo_id: str = "hexgrad/Kokoro-82M",
        model_path: str | None = None,
        device: str | None = None,
        lang_code: str = "z",
        speed: float = 1.0,
        glados_effect: dict[str, Any] | None = None,
    ):
        """
        Initialize Kokoro TTS.

        Args:
            voice: Voice name (e.g. 'zf_xiaobei' for Chinese female)
            model_repo_id: HuggingFace repo for model weights
            model_path: Local .pt model path (auto-download if None)
            device: 'cpu', 'cuda', or None for auto
            lang_code: 'z'=Chinese, 'a'=US English
            speed: Speech speed multiplier (0.5-2.0)
            glados_effect: GLaDOS effects dict, or None to disable
        """
        self.voice = voice
        self.model_repo_id = model_repo_id
        self.model_path = model_path
        self.device = device or "cpu"
        self.lang_code = lang_code
        self.speed = speed

        # GLaDOS effects processor
        if glados_effect and glados_effect.get("enabled", True):
            self._effect_processor = GladosEffectProcessor(glados_effect)
        else:
            self._effect_processor = None

        # Lazy-loaded pipeline (created on first synthesize)
        self._pipeline = None
        self._model = None

        logger.info(
            f"[KokoroTTS] Initialized: voice={voice}, lang={lang_code}, "
            f"device={self.device}, glados={'enabled' if self._effect_processor else 'disabled'}"
        )

    @classmethod
    def from_config(cls, config, **kwargs) -> KokoroTTS:
        """Create instance from KokoroTTSConfig."""
        return cls(
            voice=getattr(config, "voice", "zf_xiaobei"),
            model_repo_id=getattr(config, "model_repo_id", "hexgrad/Kokoro-82M"),
            model_path=getattr(config, "model_path", None),
            device=getattr(config, "device", "cpu"),
            lang_code=getattr(config, "lang_code", "z"),
            speed=getattr(config, "speed", 1.0),
            glados_effect=getattr(config, "glados_effect", None),
        )

    def _ensure_pipeline(self):
        """
        Lazy-load the Kokoro KPipeline on first use.

        This downloads the model from HuggingFace if not cached locally.
        Subsequent calls reuse the cached pipeline.
        """
        if self._pipeline is not None:
            return

        logger.info(f"[KokoroTTS] Loading Kokoro model (repo: {self.model_repo_id})...")

        try:
            from kokoro import KPipeline

            # Create the pipeline (automatically loads KModel)
            # Note: v0.7.x KPipeline doesn't accept repo_id; model loads
            # from hexgrad/Kokoro-82M by default
            self._pipeline = KPipeline(
                lang_code=self.lang_code,
                device=self.device,
            )

            logger.info(
                f"[KokoroTTS] Model loaded successfully "
                f"(device={self.device})"
            )

        except ImportError as e:
            logger.error(
                "[KokoroTTS] Failed to import kokoro. "
                "Install with: pip install kokoro misaki[zh]"
            )
            raise ImportError(
                "kokoro package not installed. "
                "Run: pip install kokoro misaki[zh]"
            ) from e

        except RuntimeError as e:
            logger.error(f"[KokoroTTS] Model loading failed: {e}")
            raise

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        voice: str | None = None,
        speed: float | None = None,
        **kwargs,
    ) -> bytes | str:
        """
        Synthesize text to speech using Kokoro.

        Args:
            text: Text to synthesize (Chinese or English)
            output_path: Optional file path to write audio to
            voice: Override voice for this call
            speed: Override speed for this call

        Returns:
            Audio bytes (WAV format), or file path string if output_path set
        """
        self._ensure_pipeline()

        actual_voice = voice or self.voice
        actual_speed = speed if speed is not None else self.speed

        logger.debug(
            f"[KokoroTTS] Synthesizing: '{text[:50]}...' "
            f"(voice={actual_voice}, speed={actual_speed})"
        )

        try:
            import torch

            # Generate audio via Kokoro pipeline
            # pipeline() is a generator yielding (graphemes, phonemes, audio_tensor)
            audio_chunks: list[torch.Tensor] = []
            for result in self._pipeline(
                text,
                voice=actual_voice,
                speed=actual_speed,
            ):
                if result.audio is not None:
                    audio_chunks.append(result.audio.cpu())

            if not audio_chunks:
                raise RuntimeError("Kokoro produced no audio output")

            # Concatenate all audio chunks
            full_audio = torch.cat(audio_chunks, dim=0) if len(audio_chunks) > 1 else audio_chunks[0]

            # Normalize to prevent clipping
            max_val = full_audio.abs().max()
            if max_val > 0:
                full_audio = full_audio / max_val

            # Convert to WAV bytes
            audio_bytes = self._tensor_to_wav_bytes(full_audio)

            # Apply GLaDOS effects if enabled
            if self._effect_processor and self._effect_processor.enabled:
                audio_bytes = await self._effect_processor.process(audio_bytes)

            logger.debug(
                f"[KokoroTTS] Generated {len(audio_bytes)} bytes of audio"
            )

            # Handle output
            if output_path is not None:
                output_path = Path(output_path)
                output_path.write_bytes(audio_bytes)
                logger.debug(f"[KokoroTTS] Saved to {output_path}")
                return str(output_path)

            # Write to temp file so downstream (output_node) can compute
            # volume envelope for Live2D lip sync
            temp_file = write_temp_bytes(audio_bytes, suffix=".wav")
            logger.debug(f"[KokoroTTS] Written to temp file: {temp_file}")
            return temp_file

        except Exception as e:
            logger.error(f"[KokoroTTS] Synthesis failed: {e}")
            raise

    def _tensor_to_wav_bytes(self, audio_tensor) -> bytes:
        """
        Convert a 1D audio tensor to WAV bytes using Python's built-in wave module.

        Args:
            audio_tensor: 1D float tensor of audio samples [-1, 1]

        Returns:
            WAV file bytes at 24000 Hz sample rate
        """
        import wave


        # Ensure 1D and convert to int16
        if audio_tensor.dim() > 1:
            audio_tensor = audio_tensor.squeeze()
        samples = (audio_tensor.numpy() * 32767).clip(-32768, 32767).astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(KOKORO_SAMPLE_RATE)
            wf.writeframes(samples.tobytes())
        return buffer.getvalue()

    async def close(self) -> None:
        """Clean up resources."""
        if self._effect_processor:
            await self._effect_processor.close()
        self._pipeline = None
        self._model = None
        logger.debug("[KokoroTTS] Resources released")
