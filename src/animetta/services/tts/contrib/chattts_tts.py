from __future__ import annotations

"""
ChatTTS implementation - open-source conversational speech synthesis
Model stored on local disk, loaded to GPU memory at startup
"""

# Status: experimental
# Last verified: 2026-05-23

import tempfile
from pathlib import Path

import numpy as np
from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from ..interface import TTSInterface


@ProviderRegistry.register_service("tts", "chattts")
class ChatTTSTTS(TTSInterface):
    """
    ChatTTS implementation
    Speech synthesis designed for dialogue scenarios, supports Chinese and English
    Model loaded from local disk to GPU memory for inference
    """

    SAMPLE_RATE = 24000

    def __init__(
        self,
        model_path: str = "E:/models/ChatTTS",
        device: str = "cuda",
        compile: bool = False,
        speaker_seed: int | None = 42,
        temperature: float = 0.3,
        top_p: float = 0.7,
        top_k: int = 20,
    ):
        """
        Initialize ChatTTS

        Args:
            model_path: Model file path (e.g. E:/models/ChatTTS)
            device: Inference device cuda / cpu
            compile: Whether to enable torch.compile (Windows: recommended False)
            speaker_seed: Speaker voice seed, consistent voice when fixed
            temperature: Generation temperature
            top_p: Nucleus sampling
            top_k: Top-k sampling
        """
        self.model_path = model_path
        self.device = device
        self.compile = compile
        self.speaker_seed = speaker_seed
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k

        self._chat = None
        self._speaker_embedding = None

    def _ensure_loaded(self):
        """Lazy-load: loads model from disk to GPU memory on first call"""
        if self._chat is not None:
            return

        try:
            import ChatTTS
            import torch
        except ImportError as e:
            logger.error("ChatTTS not installed, please run: pip install ChatTTS")
            raise ImportError(
                "ChatTTS 未安装，请运行: pip install ChatTTS"
            ) from e

        logger.info(f"Loading ChatTTS model from {self.model_path} to {self.device}...")

        self._chat = ChatTTS.Chat()
        self._chat.load(
            source='custom',
            custom_path=self.model_path,
            device=self.device,
            compile=self.compile,
        )

        # Fix speaker voice to ensure consistent output each time
        if self.speaker_seed is not None:
            import torch
            torch.manual_seed(self.speaker_seed)
            self._speaker_embedding = self._chat.sample_random_speaker()
            logger.info(f"Speaker voice fixed (seed={self.speaker_seed})")

        logger.info("ChatTTS model loaded successfully")

    async def preload(self) -> None:
        """Preload the ChatTTS model from disk to GPU (idempotent)"""
        if self._chat is not None:
            logger.debug("ChatTTS model already loaded, skipping preload")
            return

        logger.info(f"Preloading ChatTTS model from {self.model_path}...")

        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ensure_loaded)

        logger.info("ChatTTS model preloaded successfully")

    @staticmethod
    def _clean_text(text: str) -> str:
        """
        Clean text, keep only characters ChatTTS can handle
        ChatTTS is very sensitive to punctuation, only supports a limited set
        """
        import re

        # Remove emoji (fixed regex range error)
        # Note: ranges must be ascending, otherwise all characters will match
        emoji_ranges = [
            '\U0001F600-\U0001F64F',  # Emoticons
            '\U0001F300-\U0001F5FF',  # Symbols & Pictographs
            '\U0001F680-\U0001F6FF',  # Transport & Map
            '\U0001F1E0-\U0001F1FF',  # Flags (Regional Indicator Symbols)
            '\U00002702-\U000027B0',  # Dingbats
            '\U000024C2-\U000025FF',  # Enclosed characters (fixed range)
            '\U00002300-\U000023FF',  # Miscellaneous Technical
            '\U00002B50-\U00002BFF',  # Misc Symbols and Arrows
            '\U0000FE00-\U0000FE0F',  # Variation Selectors
            '\U0001F900-\U0001F9FF',  # Supplemental Symbols and Pictographs
            '\U0001FA00-\U0001FA6F',  # Chess Symbols
            '\U0001FA70-\U0001FAFF',  # Symbols and Pictographs Extended-A
        ]
        emoji_pattern = re.compile('[' + ''.join(emoji_ranges) + ']+', flags=re.UNICODE)
        text = emoji_pattern.sub('', text)

        # Sentence-ending punctuation -> comma
        for char in ['。', '！', '？', '!', '?', '；', ';']:
            text = text.replace(char, '，')

        # Remove all other punctuation (use character loop to avoid regex encoding issues)
        punctuation_to_remove = '：:「」『』""''""（）()[]【】《》~——…·•'
        for char in punctuation_to_remove:
            text = text.replace(char, '')

        # Remove extra commas, only trim leading/trailing commas
        while '，，' in text:
            text = text.replace('，，', '，')
        # Delete leading/trailing commas (full-width and half-width)
        text = text.strip('，')
        text = text.strip(',')

        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _build_params(self):
        """Build inference parameters"""
        import ChatTTS

        params = ChatTTS.Chat.InferCodeParams(
            temperature=self.temperature,
            top_P=self.top_p,
            top_K=self.top_k,
            spk_emb=self._speaker_embedding,
        )
        return params

    def _wav_to_bytes(self, wav_array: np.ndarray) -> bytes:
        """Convert numpy audio array to WAV format byte stream"""
        import struct

        # Normalize and convert to int16
        if wav_array.dtype != np.int16:
            # Clip to [-1, 1] to prevent overflow
            wav_array = np.clip(wav_array, -1.0, 1.0)
            wav_array = (wav_array * 32767).astype(np.int16)

        # Build WAV file header
        num_samples = len(wav_array)
        data_size = num_samples * 2  # int16 = 2 bytes
        channels = 1
        sample_width = 2
        byte_rate = self.SAMPLE_RATE * channels * sample_width
        block_align = channels * sample_width

        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',
            36 + data_size,
            b'WAVE',
            b'fmt ',
            16,               # fmt chunk size
            1,                # PCM format
            channels,
            self.SAMPLE_RATE,
            byte_rate,
            block_align,
            sample_width * 8, # bits per sample
            b'data',
            data_size,
        )

        return header + wav_array.tobytes()

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        voice: str | None = None,
        **kwargs
    ) -> bytes | str:
        """
        Synthesize text to speech

        Args:
            text: Text to synthesize
            output_path: Output file path (optional)
            voice: Reserved parameter, ChatTTS uses speaker_seed for voice control
            **kwargs: Additional parameters

        Returns:
            Union[bytes, str]: If output_path is specified, returns the file path string
                               Otherwise returns WAV audio byte data
        """
        # Ensure model is loaded
        self._ensure_loaded()

        # Clean text: full-width punctuation, emoji, etc. that ChatTTS does not support
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            logger.warning(f"ChatTTS text empty after cleaning, original: {text}")
            silence = np.zeros(self.SAMPLE_RATE, dtype=np.float32)
            audio_bytes = self._wav_to_bytes(silence)
            temp_file = tempfile.mktemp(suffix=".wav")
            with open(temp_file, "wb") as f:
                f.write(audio_bytes)
            return temp_file

        logger.debug(f"ChatTTS cleaned text: {cleaned_text}")

        try:
            params = self._build_params()

            # ChatTTS.infer is synchronous blocking, place in thread pool to avoid blocking event loop
            import asyncio
            loop = asyncio.get_event_loop()
            wavs = await loop.run_in_executor(
                None,
                lambda: self._chat.infer(
                    [cleaned_text],
                    params_infer_code=params,
                )
            )

            # Check if returned result is valid
            if wavs is None or len(wavs) == 0 or wavs[0] is None:
                logger.warning("ChatTTS returned empty result, using silence instead")
                silence = np.zeros(self.SAMPLE_RATE, dtype=np.float32)
                audio_bytes = self._wav_to_bytes(silence)
                temp_file = tempfile.mktemp(suffix=".wav")
                with open(temp_file, "wb") as f:
                    f.write(audio_bytes)
                return temp_file

            # wavs[0] is a numpy array
            wav_array = wavs[0]
            if wav_array.ndim > 1:
                wav_array = wav_array.flatten()

            if len(wav_array) == 0:
                logger.warning("ChatTTS generated empty audio, using silence instead")
                silence = np.zeros(self.SAMPLE_RATE, dtype=np.float32)
                audio_bytes = self._wav_to_bytes(silence)
                temp_file = tempfile.mktemp(suffix=".wav")
                with open(temp_file, "wb") as f:
                    f.write(audio_bytes)
                return temp_file

            audio_bytes = self._wav_to_bytes(wav_array)

            if output_path is not None:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)
                logger.debug(
                    f"ChatTTS synthesis complete: {len(text)} chars -> {output_path}"
                )
                return str(output_path)
            else:
                # Write to temp file and return path (consistent with EdgeTTS behavior)
                temp_file = tempfile.mktemp(suffix=".wav")
                with open(temp_file, "wb") as f:
                    f.write(audio_bytes)
                logger.debug(
                    f"ChatTTS synthesis complete: {len(text)} chars -> {temp_file}"
                )
                return temp_file

        except Exception as e:
            error_msg = str(e)
            if "narrow()" in error_msg:
                logger.warning(f"ChatTTS narrow() error (known issue), text: {cleaned_text}")
                silence = np.zeros(self.SAMPLE_RATE, dtype=np.float32)
                audio_bytes = self._wav_to_bytes(silence)
                if output_path is not None:
                    output_path = Path(output_path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(audio_bytes)
                    return str(output_path)
                temp_file = tempfile.mktemp(suffix=".wav")
                with open(temp_file, "wb") as f:
                    f.write(audio_bytes)
                return temp_file
            logger.error(f"ChatTTS synthesis failed: {e}")
            raise

    async def close(self) -> None:
        """Release GPU memory resources"""
        if self._chat is not None:
            # Release model references, let GC reclaim memory
            self._chat = None
            self._speaker_embedding = None

            # Actively clear CUDA cache
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

            logger.info("ChatTTS resources released, GPU memory cleared")

    @classmethod
    def from_config(cls, config: ChatTTSConfig) -> ChatTTSTTS:
        """Create instance from configuration"""
        return cls(
            model_path=config.model_path,
            device=config.device,
            compile=config.compile,
            speaker_seed=config.speaker_seed,
            temperature=config.temperature,
            top_p=config.top_p,
            top_k=config.top_k,
        )
