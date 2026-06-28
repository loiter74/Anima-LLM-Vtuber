from __future__ import annotations

"""
VibeVoice TTS implementation - Microsoft open-source long-text multi-speaker speech synthesis

Dual-mode architecture:
- Remote mode: Calls local VibeVoice HTTP inference service via httpx (recommended)
- Local mode: Calls local model inference via subprocess (alternative)

For local RTX 5090D, Remote mode + persistent FastAPI inference service is recommended.
"""

# Status: maintained
# Last verified: 2026-05-23

import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from ..interface import TTSInterface


@ProviderRegistry.register_service("tts", "vibe_voice")
class VibeVoiceTTS(TTSInterface):
    """
    VibeVoice TTS implementation

    Supports two deployment modes: remote (HTTP API) and local (subprocess inference).
    Follows GLM TTS's remote API calling pattern, extended with local inference support.

    Remote mode:
        POST to {base_url}/tts via httpx.AsyncClient
        Request body: {"text": str, "voice": str, "language": str, "num_speakers": int}
        Response: audio/wav bytes

    Local mode:
        Calls vibe_infer.py via asyncio.create_subprocess_exec
        Output audio passed through temp file
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "vibe-voice-1.5b",
        voice: str = "default",
        base_url: str = "http://localhost:8765",
        mode: str = "remote",
        model_size: str = "1.5b",
        model_path: str | None = None,
        device: str = "cuda:0",
        num_speakers: int = 1,
        language: str = "zh",
    ):
        """
        Initialize VibeVoice TTS

        Args:
            api_key: API Key (required for remote mode)
            model: Model name identifier
            voice: Default voice
            base_url: Inference service address (remote mode)
            mode: Deployment mode "remote" / "local"
            model_size: Model size "1.5b" / "7b" (local mode)
            model_path: Model weight path (local mode, default HuggingFace)
            device: Inference device (local mode)
            num_speakers: Number of speakers 1-4
            language: Language
        """
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.model_size = model_size
        self.model_path = model_path
        self.device = device
        self.num_speakers = num_speakers
        self.language = language
        self._client = None

    def _get_client(self):
        """Lazy-load HTTP client (used by remote mode)"""
        if self._client is None:
            try:
                import httpx
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=180.0,  # Long text synthesis may take time
                    headers={
                        "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
                        "Content-Type": "application/json",
                    },
                )
                logger.info(
                    f"VibeVoice HTTP client initialized (base_url={self.base_url})"
                )
            except ImportError as e:
                logger.error("httpx not installed, please run: pip install httpx")
                raise ImportError("httpx not installed，请运行: pip install httpx") from e
        return self._client

    @classmethod
    def from_config(cls, config: VibeVoiceTTSConfig, **kwargs) -> VibeVoiceTTS:
        """Create instance from config object (supports ProviderRegistry.create_service path)"""
        return cls(
            api_key=config.api_key,
            model=getattr(config, "model", "vibe-voice-1.5b"),
            voice=config.voice,
            base_url=getattr(config, "base_url", "http://localhost:8765"),
            mode=config.mode,
            model_size=config.model_size,
            model_path=config.model_path,
            device=config.device,
            num_speakers=config.num_speakers,
            language=config.language,
        )

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        voice: str | None = None,
        **kwargs,
    ) -> bytes | str:
        """
        Synthesize text to speech

        Args:
            text: Text to synthesize
            output_path: Output file path (optional)
            voice: Voice (optional, overrides default)
            **kwargs: Additional parameters (can override num_speakers, language, etc.)

        Returns:
            Union[bytes, str]: If output_path is specified, returns the file path string
                               Otherwise returns audio byte data
        """
        if not text or not text.strip():
            logger.warning("VibeVoice TTS received empty text, skipping synthesis")
            return b"" if output_path is None else str(output_path)

        logger.debug(
            f"VibeVoice TTS synthesis: text_len={len(text)}, "
            f"mode={self.mode}, voice={voice or self.voice}"
        )

        try:
            if self.mode == "remote":
                return await self._synthesize_remote(
                    text=text,
                    output_path=output_path,
                    voice=voice or self.voice,
                    num_speakers=kwargs.get("num_speakers", self.num_speakers),
                    language=kwargs.get("language", self.language),
                )
            else:
                return await self._synthesize_local(
                    text=text,
                    output_path=output_path,
                    voice=voice or self.voice,
                )
        except Exception as e:
            logger.error(f"VibeVoice TTS synthesis failed: {e}")
            raise

    async def _synthesize_remote(
        self,
        text: str,
        output_path: str | Path | None,
        voice: str,
        num_speakers: int,
        language: str,
    ) -> bytes | str:
        """Synthesize speech via HTTP API"""
        import httpx

        client = self._get_client()

        payload = {
            "text": text,
            "voice": voice,
            "language": language,
            "num_speakers": num_speakers,
        }

        try:
            response = await client.post("/tts", json=payload)
            response.raise_for_status()

            audio_data = response.content

            if not audio_data:
                raise RuntimeError("VibeVoice service returned empty audio data")

            logger.debug(
                f"VibeVoice remote synthesis successful: {len(audio_data)} bytes, "
                f"voice={voice}, speakers={num_speakers}"
            )

            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_data)
                logger.info(f"VibeVoice audio saved to: {output_path}")
                return str(output_path)
            return audio_data

        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Unable to connect to VibeVoice service ({self.base_url})."
                f"Please ensure the inference service is running."
            ) from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"VibeVoice service returned error: {e.response.status_code} "
                f"{e.response.text}"
            ) from e

    async def _synthesize_local(
        self,
        text: str,
        output_path: str | Path | None,
        voice: str,
    ) -> bytes | str:
        """Synthesize speech via subprocess local inference"""
        if output_path:
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            out_file = Path(tempfile.mktemp(suffix=".wav"))

        # Build inference command
        infer_script = self._find_infer_script()
        cmd = [
            "python", infer_script,
            "--text", text,
            "--output", str(out_file),
            "--device", self.device,
        ]
        if self.model_path:
            cmd.extend(["--model", self.model_path])
        if self.model_size:
            cmd.extend(["--model-size", self.model_size])

        logger.debug(f"VibeVoice local inference: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise RuntimeError(
                    f"VibeVoice local inference failed (exit={process.returncode}): {error_msg}"
                )

            if not out_file.exists() or out_file.stat().st_size == 0:
                raise RuntimeError("VibeVoice local inference did not generate audio file")

            logger.debug(
                f"VibeVoice local synthesis successful: {out_file.stat().st_size} bytes"
            )

            if output_path:
                return str(out_file)
            else:
                audio_data = out_file.read_bytes()
                out_file.unlink(missing_ok=True)  # Clean up temp file
                return audio_data

        except FileNotFoundError as e:
            raise RuntimeError(
                "VibeVoice inference script not found. Please ensure the model is downloaded and model_path is configured."
            ) from e

    def _find_infer_script(self) -> str:
        """Find VibeVoice inference script path"""
        candidates = [
            os.path.expanduser("~/VibeVoice/demo/tts_1p5b_inference.py"),
            os.path.expanduser("~/VibeVoice/demo/vibevoice_realtime_demo.py"),
        ]
        if self.model_path:
            parents = Path(self.model_path).parents
            for p in parents:
                demo_dir = p / "demo"
                if (demo_dir / "tts_1p5b_inference.py").exists():
                    return str(demo_dir / "tts_1p5b_inference.py")

        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        # Default return, let the caller handle FileNotFoundError
        return "vibe_infer.py"

    async def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[bytes]:
        """
        Streaming speech synthesis (Remote mode supports streaming response)

        Yields:
            bytes: Audio data chunks
        """

        if self.mode != "remote":
            # Local mode does not support streaming, fallback to full synthesis
            audio = await self._synthesize_local(
                text=text,
                output_path=None,
                voice=voice or self.voice,
            )
            yield audio
            return

        client = self._get_client()
        payload = {
            "text": text,
            "voice": voice or self.voice,
            "language": kwargs.get("language", self.language),
            "num_speakers": kwargs.get("num_speakers", self.num_speakers),
            "stream": True,
        }

        try:
            async with client.stream("POST", "/tts/stream", json=payload) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except Exception as e:
            logger.error(f"VibeVoice streaming synthesis failed: {e}")
            raise

    async def close(self) -> None:
        """Clean up resources"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("VibeVoice HTTP client closed")
