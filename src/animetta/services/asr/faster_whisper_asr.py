from __future__ import annotations

"""
Faster-Whisper ASR implementation - open-source free speech recognition
Based on faster-whisper project: https://github.com/guillaumekln/faster-whisper

Supports multiple models:
- tiny: fastest, lower accuracy
- base: balances speed and accuracy
- small: faster, moderate accuracy
- medium: slower, high accuracy
- large-v2: slowest, highest accuracy (recommended for Chinese)
- large-v3: latest version

Supports Chinese models:
- distil-large-v3: recommended, fast and accurate
- distil-medium.en: English only
"""

from pathlib import Path

import numpy as np
from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import ASRInterface


@ProviderRegistry.register_service("asr", "faster_whisper")
class FasterWhisperASR(ASRInterface):
    """
    Faster-Whisper ASR implementation
    Optimized version of the OpenAI Whisper model, fast and fully offline
    """

    # Supported model list
    MODELS = {
        "tiny": "tiny",
        "base": "base",
        "small": "small",
        "medium": "medium",
        "large-v2": "large-v2",
        "large-v3": "large-v3",
        "distil-small.en": "distil-small.en",
        "distil-medium.en": "distil-medium.en",
        "distil-large-v3": "distil-large-v3",  # Recommended: supports multiple languages, fast
        "systran/faster-whisper-large-v3": "systran/faster-whisper-large-v3",
    }

    def __init__(
        self,
        model: str = "distil-large-v3",
        language: str = "zh",  # Default Chinese
        device: str = "auto",  # auto, cpu, cuda
        compute_type: str = "default",  # default, int8, float16, float32
        download_root: str | None = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        vad_parameters: dict = None,
    ):
        """
        Initialize Faster-Whisper ASR

        Args:
            model: Model name or path (default distil-large-v3)
            language: Language code (zh=Chinese, en=English, ja=Japanese, etc.)
            device: Device (auto=auto-detect, cpu=CPU, cuda=CUDA)
            compute_type: Compute type (default=auto, int8=quantization, float16=half precision)
            download_root: Model download root directory
            beam_size: Beam search size (1-10, larger is more accurate but slower)
            vad_filter: Whether to use VAD to filter silence
            vad_parameters: VAD parameters
        """
        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.vad_parameters = vad_parameters or {}
        self._model = None

        logger.info("Faster-Whisper ASR initialization config:")
        logger.info(f"  Model: {model}")
        logger.info(f"  Language: {language}")
        logger.info(f"  Device: {device}")
        logger.info(f"  Compute type: {compute_type}")
        logger.info(f"  Beam Size: {beam_size}")
        logger.info(f"  VAD filter: {vad_filter}")

    def _get_model(self):
        """Lazy-load model"""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel

                logger.info(f"Loading Faster-Whisper model: {self.model_name}...")
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=self.download_root,
                )
                logger.info("Faster-Whisper model loaded successfully")

            except ImportError:
                logger.error("faster-whisper not installed, please run: pip install faster-whisper")
                raise ImportError(
                    "faster-whisper 未安装，请运行: pip install faster-whisper"
                )
            except Exception as e:
                logger.error(f"Failed to load Faster-Whisper model: {e}")
                raise

        return self._model

    async def preload(self) -> None:
        """Preload the model (idempotent - safe to call multiple times)"""
        if self._model is not None:
            logger.debug("Faster-Whisper model already loaded, skipping preload")
            return

        logger.info(f"Preloading Faster-Whisper model: {self.model_name}...")

        # Run model loading in thread pool (CPU-intensive operation)
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._get_model)

        logger.info("Faster-Whisper model preloaded successfully")

    async def transcribe(
        self,
        audio_data: bytes | str | Path | list | np.ndarray,
        **kwargs
    ) -> str:
        """
        Transcribe audio data to text

        Args:
            audio_data: Audio data, can be:
                - bytes: Byte data in WAV/MP3 etc. format
                - str/Path: Audio file path
                - list/numpy array: PCM audio data (float32, range [-1.0, 1.0])

        Returns:
            str: Recognized text
        """
        import asyncio

        self._get_model()

        # Process input data, convert to numpy array
        if isinstance(audio_data, np.ndarray):
            audio_np = audio_data
        elif isinstance(audio_data, list):
            audio_np = np.array(audio_data, dtype=np.float32)
        elif isinstance(audio_data, (str, Path)):
            # Read and decode from file
            audio_np = await self._load_audio_file(str(audio_data))
        elif isinstance(audio_data, bytes):
            # Decode audio from bytes
            audio_np = await self._load_audio_bytes(audio_data)
        else:
            raise ValueError(f"Unsupported audio data type: {type(audio_data)}")

        # Ensure float32 format
        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32)

        # Clip range to [-1.0, 1.0]
        audio_np = np.clip(audio_np, -1.0, 1.0)

        logger.debug(f"Faster-Whisper ASR processing audio: {len(audio_np)} samples")

        # Run transcription in thread pool (CPU-intensive operation)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._transcribe_sync,
            audio_np
        )

        logger.info(f"Faster-Whisper ASR recognition result: {result}")
        return result

    def _transcribe_sync(self, audio_np: np.ndarray) -> str:
        """Synchronous transcription method"""
        model = self._get_model()

        # Configure parameters
        parameters = {
            "beam_size": self.beam_size,
            "language": self.language if self.language else None,
            "task": "transcribe",
            "condition_on_previous_text": False,
            "vad_filter": self.vad_filter,
        }

        # Add VAD parameters
        if self.vad_filter:
            parameters.update({
                "vad_parameters": {
                    "min_silence_duration_ms": self.vad_parameters.get("min_silence_duration_ms", 500),
                    "speech_pad_ms": self.vad_parameters.get("speech_pad_ms", 30),
                }
            })

        # Log language configuration
        logger.debug(f"Faster-Whisper config - language={self.language}, parameters={parameters}")

        # Execute transcription
        segments, info = model.transcribe(audio_np, **parameters)

        # Log detected language info
        logger.info(f"Faster-Whisper detection info: language='{info.language}', language_probability={info.language_probability:.2f}")

        # Extract text
        text_parts = [segment.text for segment in segments]

        if not text_parts:
            return ""

        text = "".join(text_parts).strip()

        # Convert Traditional Chinese to Simplified Chinese
        try:
            from opencc import OpenCC
            converter = OpenCC('t2s')  # Traditional → Simplified
            text = converter.convert(text)
        except ImportError:
            pass  # opencc not installed, skip conversion

        return text

    async def _load_audio_file(self, file_path: str) -> np.ndarray:
        """Load audio from file"""
        # Load audio using pydub (supports multiple formats)
        try:
            from pydub import AudioSegment

            audio_segment = AudioSegment.from_file(file_path)
            samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)

            # Normalize to [-1.0, 1.0]
            if audio_segment.sample_width == 2:  # 16-bit
                samples = samples / 32768.0
            elif audio_segment.sample_width == 4:  # 32-bit
                samples = samples / 2147483648.0

            # Convert to mono
            if audio_segment.channels > 1:
                samples = samples.reshape((-1, audio_segment.channels)).mean(axis=1)

            # Resample to 16kHz (if needed)
            if audio_segment.frame_rate != 16000:
                # Simple resampling method (can use librosa or resampy for better results)
                ratio = 16000 / audio_segment.frame_rate
                target_length = int(len(samples) * ratio)
                samples = np.interp(
                    np.linspace(0, len(samples), target_length),
                    np.arange(len(samples)),
                    samples
                )

            logger.debug(f"Loaded audio file: {file_path}, samples: {len(samples)}")
            return samples

        except ImportError:
            logger.warning("pydub not installed, using wave module (only supports WAV)")
            # Fallback to wave module
            import wave

            with wave.open(file_path, 'rb') as wf:
                sample_rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)

                # Normalize and convert to float32
                samples = audio_data.astype(np.float32) / 32768.0

                # Resample to 16kHz
                if sample_rate != 16000:
                    ratio = 16000 / sample_rate
                    target_length = int(len(samples) * ratio)
                    samples = np.interp(
                        np.linspace(0, len(samples), target_length),
                        np.arange(len(samples)),
                        samples
                    )

                return samples

    async def _load_audio_bytes(self, audio_bytes: bytes) -> np.ndarray:
        """Load int16 PCM audio bytes directly (no temp file / ffmpeg needed)."""
        # VAD delivers 16kHz mono int16 PCM — decode directly to float32 [-1, 1]
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return audio_np

    async def transcribe_stream(
        self,
        audio_data: bytes | str | Path | list | np.ndarray,
        **kwargs
    ):
        """
        Stream recognition of audio, generator returns text chunks

        Args:
            audio_data: Audio data

        Yields:
            str: Recognized text chunks
        """
        # Faster-Whisper does not support true streaming, but we can simulate it
        result = await self.transcribe(audio_data, **kwargs)

        # Split by sentences and return
        import re
        sentences = re.split(r'[。！？.!?]', result)

        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                yield sentence

    async def close(self) -> None:
        """Clean up resources"""
        self._model = None
        logger.debug("Faster-Whisper ASR resources released")

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from configuration"""
        return cls(
            model=getattr(config, "model", "distil-large-v3"),
            language=getattr(config, "language", "zh"),
            device=getattr(config, "device", "auto"),
            compute_type=getattr(config, "compute_type", "default"),
            download_root=getattr(config, "download_root", None),
            beam_size=getattr(config, "beam_size", 5),
            vad_filter=getattr(config, "vad_filter", True),
            vad_parameters=getattr(config, "vad_parameters", {}),
        )
