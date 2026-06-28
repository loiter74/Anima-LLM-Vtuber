from __future__ import annotations

"""
GLM TTS implementation - uses Zhipu AI GLM TTS API
"""

# Status: maintained
# Last verified: 2026-05-23

from pathlib import Path

from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from ..interface import TTSInterface


@ProviderRegistry.register_service("tts", "glm")
class GLMTTS(TTSInterface):
    """
    GLM TTS implementation
    Uses Zhipu AI's GLM TTS API for speech synthesis
    """

    def __init__(
        self,
        api_key: str,
        model: str = "glm-tts",
        voice: str = "female",
        response_format: str = "wav",
        speed: float = 1.0,
        volume: float = 1.0,
    ):
        """
        Initialize GLM TTS client

        Args:
            api_key: Zhipu AI API Key
            model: TTS model, defaults to glm-tts
            voice: Voice, options: male/female
            response_format: Output format, supports wav/mp3/pcm
            speed: Speaking speed, range 0.5-2.0
            volume: Volume, range 0.5-2.0
        """
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.response_format = response_format
        self.speed = speed
        self.volume = volume
        self._client = None

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from configuration (supports ProviderRegistry.create_service path)"""
        return cls(
            api_key=config.api_key,
            model=getattr(config, "model", "glm-tts"),
            voice=config.voice,
            response_format=getattr(config, "response_format", "wav"),
            speed=getattr(config, "speed", 1.0),
            volume=getattr(config, "volume", 1.0),
        )

    def _get_client(self):
        """Lazy-load client"""
        if self._client is None:
            try:
                from zai import ZhipuAiClient
                self._client = ZhipuAiClient(api_key=self.api_key)
                logger.info("GLM TTS client initialized successfully")
            except ImportError as e:
                logger.error("zai-sdk not installed, please run: pip install zai-sdk")
                raise ImportError(
                    "zai-sdk 未安装，请运行: pip install zai-sdk"
                ) from e
        return self._client

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        voice: str | None = None,
        speed: float | None = None,
        volume: float | None = None,
        response_format: str | None = None,
        stream: bool = False,
        **kwargs
    ) -> bytes | str:
        """
        Synthesize text to speech

        Args:
            text: Text to synthesize
            output_path: Output file path (optional)
            voice: Voice (optional, overrides default)
            speed: Speaking speed (optional, overrides default)
            volume: Volume (optional, overrides default)
            response_format: Output format (optional, overrides default)
            stream: Whether to use streaming
            **kwargs: Additional parameters

        Returns:
            Union[bytes, str]: If output_path is specified, returns the file path string
                               Otherwise returns audio byte data
        """
        client = self._get_client()

        # Use passed parameters or defaults
        actual_voice = voice or self.voice
        actual_speed = speed if speed is not None else self.speed
        actual_volume = volume if volume is not None else self.volume
        actual_format = response_format or self.response_format

        logger.debug(f"GLM TTS synthesizing text: {text[:50]}... (voice={actual_voice}, format={actual_format})")

        try:
            if stream:
                # Streaming call
                return await self._synthesize_stream(
                    client, text, output_path, actual_voice, actual_format, actual_speed, actual_volume
                )
            else:
                # Non-streaming call
                return await self._synthesize_sync(
                    client, text, output_path, actual_voice, actual_format, actual_speed, actual_volume
                )
        except Exception as e:
            logger.error(f"GLM TTS synthesis failed: {e}")
            raise

    async def _synthesize_sync(
        self,
        client,
        text: str,
        output_path: str | Path | None,
        voice: str,
        response_format: str,
        speed: float,
        volume: float
    ) -> bytes | str:
        """Non-streaming synthesis"""
        import asyncio

        # Execute synchronous call in thread pool
        loop = asyncio.get_event_loop()

        def _call_api():
            response = client.audio.speech(
                model=self.model,
                input=text,
                voice=voice,
                response_format=response_format,
                speed=speed,
                volume=volume
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        if output_path:
            # Save to file
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            response.stream_to_file(str(output_path))
            logger.info(f"GLM TTS audio saved to: {output_path}")
            return str(output_path)
        else:
            # Return byte data
            import io
            buffer = io.BytesIO()
            for chunk in response.iter_bytes():
                buffer.write(chunk)
            audio_data = buffer.getvalue()
            logger.debug(f"GLM TTS returning audio data: {len(audio_data)} bytes")
            return audio_data

    async def _synthesize_stream(
        self,
        client,
        text: str,
        output_path: str | Path | None,
        voice: str,
        response_format: str,
        speed: float,
        volume: float
    ) -> bytes | str:
        """Streaming synthesis"""
        import asyncio
        import base64

        loop = asyncio.get_event_loop()

        def _call_api():
            response = client.audio.speech(
                model=self.model,
                input=text,
                voice=voice,
                stream=True,
                response_format='pcm',
                encode_format='base64',
                speed=speed,
                volume=volume
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        # Collect all audio data
        audio_chunks = []

        for chunk in response:
            for choice in chunk.choices:
                is_finished = choice.finish_reason
                if is_finished == "stop":
                    break
                audio_delta = choice.delta.content
                if audio_delta:
                    # Decode base64 data
                    audio_data = base64.b64decode(audio_delta)
                    audio_chunks.append(audio_data)

        # Merge all audio data
        all_audio = b''.join(audio_chunks)

        if output_path:
            # Save to file
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(all_audio)
            logger.info(f"GLM TTS streaming audio saved to: {output_path}")
            return str(output_path)
        else:
            logger.debug(f"GLM TTS streaming returning audio data: {len(all_audio)} bytes")
            return all_audio

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        speed: float | None = None,
        volume: float | None = None,
        **kwargs
    ):
        """
        Streaming speech synthesis, generator yields audio chunks

        Args:
            text: Text to synthesize
            voice: Voice
            speed: Speaking speed
            volume: Volume

        Yields:
            bytes: Audio data chunks
        """
        import asyncio
        import base64

        client = self._get_client()

        actual_voice = voice or self.voice
        actual_speed = speed if speed is not None else self.speed
        actual_volume = volume if volume is not None else self.volume

        loop = asyncio.get_event_loop()

        def _call_api():
            response = client.audio.speech(
                model=self.model,
                input=text,
                voice=actual_voice,
                stream=True,
                response_format='pcm',
                encode_format='base64',
                speed=actual_speed,
                volume=actual_volume
            )
            return response

        response = await loop.run_in_executor(None, _call_api)

        for chunk in response:
            for choice in chunk.choices:
                is_finished = choice.finish_reason
                if is_finished == "stop":
                    return
                audio_delta = choice.delta.content
                if audio_delta:
                    # Decode base64 data and yield
                    audio_data = base64.b64decode(audio_delta)
                    yield audio_data

    async def close(self) -> None:
        """Clean up resources"""
        self._client = None
        logger.debug("GLM TTS client closed")
