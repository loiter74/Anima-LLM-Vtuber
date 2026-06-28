from __future__ import annotations

"""
GLM ASR implementation - uses Zhipu AI GLM ASR API
"""

import io
from pathlib import Path

from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import ASRInterface


@ProviderRegistry.register_service("asr", "glm")
class GLMASR(ASRInterface):
    """
    GLM ASR implementation
    Uses Zhipu AI's GLM ASR API for speech recognition
    """

    @staticmethod
    def _convert_to_supported_audio_bytes(audio_data, sample_rate: int = 16000) -> tuple[bytes, str]:
        """
        Convert audio data to a format supported by GLM ASR

        GLM ASR supported formats: MP3, WAV (with specific encoding), FLAC, M4A, OGG

        Args:
            audio_data: Can be one of the following types:
                - numpy array (float32, range [-1.0, 1.0])
                - list of floats
                - bytes (already in audio format)
            sample_rate: Sample rate, default 16000

        Returns:
            tuple[bytes, str]: (audio data, file extension)
        """
        # If already bytes, assume it's a supported format
        if isinstance(audio_data, bytes):
            return audio_data, "mp3"

        # Convert to numpy array
        try:
            import numpy as np
            if isinstance(audio_data, list):
                audio_np = np.array(audio_data, dtype=np.float32)
            else:
                audio_np = audio_data
        except ImportError:
            logger.error("numpy is required, install: pip install numpy")
            raise

        # Try to convert to MP3 using pydub (more reliable)
        try:
            import io

            from pydub import AudioSegment

            # Convert numpy array to AudioSegment
            if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
                audio_np = np.clip(audio_np, -1.0, 1.0)
                int16_data = (audio_np * 32767).astype(np.int16)
            else:
                int16_data = audio_np.astype(np.int16)

            # Create AudioSegment
            audio_segment = AudioSegment(
                data=int16_data.tobytes(),
                sample_width=2,  # 16-bit
                frame_rate=sample_rate,
                channels=1  # Mono
            )

            # Export as MP3
            mp3_buffer = io.BytesIO()
            audio_segment.export(mp3_buffer, format="mp3", bitrate="64k")
            mp3_buffer.seek(0)

            logger.debug(f"Audio converted to MP3: {len(mp3_buffer.getvalue())} bytes")
            return mp3_buffer.getvalue(), "mp3"

        except ImportError:
            logger.warning("pydub not installed, using WAV format (pip install pydub)")
            # Fallback to WAV format
            import wave

            if audio_np.dtype == np.float32 or audio_np.dtype == np.float64:
                audio_np = np.clip(audio_np, -1.0, 1.0)
                int16_data = (audio_np * 32767).astype(np.int16)
            else:
                int16_data = audio_np.astype(np.int16)

            wav_buffer = io.BytesIO()

            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(int16_data.tobytes())

            wav_buffer.seek(0)
            return wav_buffer.read(), "wav"

    def __init__(
        self,
        api_key: str,
        model: str = "glm-asr-2512",
        stream: bool = False,
    ):
        """
        Initialize GLM ASR client

        Args:
            api_key: Zhipu AI API Key
            model: ASR model, defaults to glm-asr-2512
            stream: Whether to use streaming call
        """
        self.api_key = api_key
        self.model = model
        self.stream = stream
        self._client = None

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from configuration (supports ProviderRegistry.create_service path)"""
        return cls(
            api_key=config.api_key,
            model=getattr(config, "model", "glm-asr-2512"),
            stream=getattr(config, "stream", False),
        )

    def _get_client(self):
        """Lazy-load client"""
        if self._client is None:
            try:
                from zai import ZhipuAiClient
                self._client = ZhipuAiClient(api_key=self.api_key)
                logger.info("GLM ASR client initialized successfully")
            except ImportError as e:
                logger.error("zai-sdk not installed, please run: pip install zai-sdk")
                raise ImportError(
                    "zai-sdk 未安装，请运行: pip install zai-sdk"
                ) from e
        return self._client

    async def transcribe(
        self,
        audio_data: bytes | str | Path | list,
        stream: bool | None = None,
        **kwargs
    ) -> str:
        """
        Transcribe audio data to text

        Args:
            audio_data: Audio data, can be:
                - bytes: Raw audio bytes (supported formats)
                - str/Path: Audio file path
                - list/numpy array: PCM audio data (float32, range [-1.0, 1.0])
            stream: Whether to use streaming call (optional, overrides default)
            **kwargs: Additional parameters

        Returns:
            str: Recognized text
        """
        client = self._get_client()

        # Use passed parameter or default
        use_stream = stream if stream is not None else self.stream

        # Process input data, get audio bytes and extension
        if isinstance(audio_data, bytes):
            audio_bytes, ext = audio_data, "mp3"
        elif isinstance(audio_data, (str, Path)):
            # Read from file
            with open(str(audio_data), 'rb') as f:
                audio_bytes = f.read()
            ext = Path(audio_data).suffix.lstrip('.')
        else:
            # Convert to supported audio format
            audio_bytes, ext = self._convert_to_supported_audio_bytes(audio_data)

        logger.debug(f"GLM ASR processing audio: {len(audio_bytes)} bytes, format: {ext} (stream={use_stream})")

        try:
            if use_stream:
                result = await self._transcribe_stream(client, audio_bytes, ext)
            else:
                result = await self._transcribe_sync(client, audio_bytes, ext)

            logger.info(f"GLM ASR recognition result: {result}")
            return result

        finally:
            pass  # bytes dont need cleanup

    async def _transcribe_sync(self, client, audio_bytes: bytes, ext: str = "mp3") -> str:
        """Non-streaming recognition"""
        import asyncio

        loop = asyncio.get_event_loop()

        def _call_api():
            # Create named BytesIO, add name attribute
            class NamedBytesIO(io.BytesIO):
                def __init__(self, data, name):
                    super().__init__(data)
                    self.name = name

            audio_file = NamedBytesIO(audio_bytes, f"audio.{ext}")

            response = client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        # Extract text result
        if hasattr(response, 'text'):
            return response.text
        elif isinstance(response, dict):
            return response.get('text', '')
        else:
            return str(response)

    async def _transcribe_stream(self, client, audio_bytes: bytes, ext: str = "mp3") -> str:
        """Streaming recognition"""
        import asyncio

        loop = asyncio.get_event_loop()

        def _call_api():
            # Create named BytesIO, add name attribute
            class NamedBytesIO(io.BytesIO):
                def __init__(self, data, name):
                    super().__init__(data)
                    self.name = name

            audio_file = NamedBytesIO(audio_bytes, f"audio.{ext}")

            response = client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        # Collect all text (if streaming response)
        full_text = []

        # Check if it's an iterable streaming response
        if hasattr(response, '__iter__') and not isinstance(response, (str, bytes, dict)):
            for chunk in response:
                if hasattr(chunk, 'text'):
                    full_text.append(chunk.text)
                elif isinstance(chunk, dict):
                    text = chunk.get('text', '')
                    if text:
                        full_text.append(text)
                elif hasattr(chunk, 'choices'):
                    for choice in chunk.choices:
                        if hasattr(choice, 'delta') and hasattr(choice.delta, 'content'):
                            content = choice.delta.content
                            if content:
                                full_text.append(content)
        else:
            # Non-streaming response, extract text directly
            if hasattr(response, 'text'):
                return response.text
            elif isinstance(response, dict):
                return response.get('text', '')
            else:
                return str(response)

        return ''.join(full_text)

    async def transcribe_stream(
        self,
        audio_data: bytes | str | Path | list,
        **kwargs
    ):
        """
        Stream recognition of audio, generator returns text chunks

        Args:
            audio_data: Audio data

        Yields:
            str: Recognized text chunks
        """
        import asyncio

        client = self._get_client()

        # Process input data, get audio bytes and extension
        if isinstance(audio_data, bytes):
            audio_bytes, ext = audio_data, "mp3"
        elif isinstance(audio_data, (str, Path)):
            with open(str(audio_data), 'rb') as f:
                audio_bytes = f.read()
            ext = Path(audio_data).suffix.lstrip('.')
        else:
            audio_bytes, ext = self._convert_to_supported_audio_bytes(audio_data)

        loop = asyncio.get_event_loop()

        def _call_api():
            # Create named BytesIO, add name attribute
            class NamedBytesIO(io.BytesIO):
                def __init__(self, data, name):
                    super().__init__(data)
                    self.name = name

            audio_file = NamedBytesIO(audio_bytes, f"audio.{ext}")

            response = client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        for chunk in response:
            text = None
            if hasattr(chunk, 'text'):
                text = chunk.text
            elif isinstance(chunk, dict):
                text = chunk.get('text', '')
            elif hasattr(chunk, 'choices'):
                for choice in chunk.choices:
                    if hasattr(choice, 'delta') and hasattr(choice.delta, 'content'):
                        text = choice.delta.content

            if text:
                yield text

    async def close(self) -> None:
        """Clean up resources"""
        self._client = None
        logger.debug("GLM ASR client closed")
