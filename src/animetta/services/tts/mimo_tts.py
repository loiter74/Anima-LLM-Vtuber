from __future__ import annotations

"""Xiaomi MiMo TTS implementation."""

import base64
from pathlib import Path
from typing import Any

from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts.mimo import MimoTTSConfig

from .interface import TTSInterface


@ProviderRegistry.register_service("tts", "mimo")
class MimoTTS(TTSInterface):
    """MiMo V2.5 speech synthesis via the OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "mimo-v2.5-tts",
        voice: str = "mimo_default",
        base_url: str = "https://api.xiaomimimo.com/v1",
        response_format: str = "wav",
        style_prompt: str | None = None,
        timeout: float = 60.0,
        http_client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.base_url = self._resolve_base_url(api_key, base_url).rstrip("/")
        self.response_format = response_format
        self.style_prompt = style_prompt
        self.timeout = timeout
        self._client = http_client

    @classmethod
    def from_config(cls, config: MimoTTSConfig, **kwargs) -> MimoTTS:
        """Create instance from configuration."""
        return cls(
            api_key=config.api_key,
            model=config.model,
            voice=config.voice,
            base_url=config.base_url,
            response_format=config.response_format,
            style_prompt=config.style_prompt,
            timeout=config.timeout,
        )

    def _get_client(self):
        """Lazy-load HTTP client."""
        if self._client is None:
            try:
                import httpx
            except ImportError as e:
                raise ImportError("httpx is required for MiMo TTS") from e

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
            logger.info(f"MiMo TTS HTTP client initialized (base_url={self.base_url})")
        return self._client

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        voice: str | None = None,
        response_format: str | None = None,
        style_prompt: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> bytes | str:
        """Synthesize text to audio bytes, or write audio bytes to output_path."""
        if not self.api_key:
            raise ValueError("MiMo TTS requires MIMO_API_KEY or TTS_API_KEY")

        if not text or not text.strip():
            if output_path is None:
                return b""
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
            return str(path)

        client = self._get_client()
        actual_voice = voice or self.voice
        actual_format = response_format or self.response_format
        payload = self._build_payload(
            text=text,
            voice=actual_voice,
            response_format=actual_format,
            style_prompt=style_prompt if style_prompt is not None else self.style_prompt,
            model=model or self.model,
        )

        logger.debug(
            f"MiMo TTS synthesizing: text_len={len(text)}, voice={actual_voice}, format={actual_format}"
        )
        response = await client.post(
            "/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        try:
            response.raise_for_status()
        except Exception as e:
            body = getattr(response, "text", "")
            raise RuntimeError(
                f"MiMo TTS request failed: status={response.status_code}, body={body[:500]}"
            ) from e

        audio_data = self._extract_audio(response.json())
        if not audio_data:
            raise RuntimeError("MiMo TTS returned empty audio data")

        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio_data)
            return str(path)
        return audio_data

    def _headers(self) -> dict[str, str]:
        return {
            "api-key": self.api_key or "",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _resolve_base_url(api_key: str | None, base_url: str) -> str:
        if (
            api_key
            and api_key.startswith("tp-")
            and base_url.rstrip("/") == "https://api.xiaomimimo.com/v1"
        ):
            return "https://token-plan-cn.xiaomimimo.com/v1"
        return base_url

    @staticmethod
    def _build_payload(
        text: str,
        voice: str,
        response_format: str,
        style_prompt: str | None,
        model: str,
    ) -> dict[str, Any]:
        messages = []
        if style_prompt:
            messages.append({"role": "user", "content": style_prompt})
        messages.append({"role": "assistant", "content": text})

        return {
            "model": model,
            "messages": messages,
            "modalities": ["text", "audio"],
            "audio": {
                "format": response_format,
                "voice": voice,
            },
            "stream": False,
        }

    @staticmethod
    def _extract_audio(payload: dict[str, Any]) -> bytes:
        try:
            audio_base64 = payload["choices"][0]["message"]["audio"]["data"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                "MiMo TTS response did not include choices[0].message.audio.data"
            ) from e

        try:
            return base64.b64decode(audio_base64, validate=True)
        except Exception as e:
            raise RuntimeError("MiMo TTS returned invalid base64 audio data") from e

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def audio_format(self) -> str:
        return self.response_format
