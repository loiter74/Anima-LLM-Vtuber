from __future__ import annotations

"""Xiaomi MiMo ASR implementation."""

import base64
import io
import wave
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.asr.mimo import MimoASRConfig

from .interface import ASRInterface


@ProviderRegistry.register_service("asr", "mimo")
class MimoASR(ASRInterface):
    """MiMo V2.5 speech recognition via the OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "mimo-v2.5-asr",
        base_url: str = "https://api.xiaomimimo.com/v1",
        language: str = "auto",
        sample_rate: int = 16000,
        input_audio_format: str = "pcm_s16le",
        timeout: float = 30.0,
        http_client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = self._resolve_base_url(api_key, base_url).rstrip("/")
        self.language = language
        self.sample_rate = sample_rate
        self.input_audio_format = input_audio_format
        self.timeout = timeout
        self._client = http_client

    @classmethod
    def from_config(cls, config: MimoASRConfig, **kwargs) -> MimoASR:
        """Create instance from configuration."""
        return cls(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            language=config.language,
            sample_rate=config.sample_rate,
            input_audio_format=config.input_audio_format,
            timeout=config.timeout,
        )

    async def transcribe(
        self,
        audio_data: bytes | str | Path | list | np.ndarray,
        audio_format: str | None = None,
        language: str | None = None,
        sample_rate: int | None = None,
        **kwargs,
    ) -> str:
        """Transcribe audio bytes, a file path, or raw PCM samples to text."""
        if not self.api_key:
            raise ValueError("MiMo ASR requires MIMO_API_KEY or ASR_API_KEY")

        payload = self._build_payload(
            audio_data,
            audio_format=audio_format,
            language=language or self.language,
            sample_rate=sample_rate or self.sample_rate,
        )
        response = await self._get_client().post(
            "/chat/completions",
            headers=self._headers(),
            json=payload,
        )
        try:
            response.raise_for_status()
        except Exception as e:
            body = getattr(response, "text", "")
            status_code = getattr(response, "status_code", "unknown")
            raise RuntimeError(
                f"MiMo ASR request failed: status={status_code}, body={body[:500]}"
            ) from e

        text = self._extract_text(response.json()).strip()
        logger.info(f"MiMo ASR recognition result: text_len={len(text)}")
        return text

    def _get_client(self):
        """Lazy-load HTTP client."""
        if self._client is None:
            try:
                import httpx
            except ImportError as e:
                raise ImportError("httpx is required for MiMo ASR") from e

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
            logger.info(f"MiMo ASR HTTP client initialized (base_url={self.base_url})")
        return self._client

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

    def _build_payload(
        self,
        audio_data: bytes | str | Path | list | np.ndarray,
        *,
        audio_format: str | None,
        language: str,
        sample_rate: int,
    ) -> dict[str, Any]:
        encoded_audio, actual_format = self._prepare_audio(
            audio_data,
            audio_format=audio_format,
            sample_rate=sample_rate,
        )
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": self._to_data_url(encoded_audio, actual_format),
                            },
                        }
                    ],
                }
            ],
            "asr_options": {"language": language},
            "stream": False,
        }

    def _prepare_audio(
        self,
        audio_data: bytes | str | Path | list | np.ndarray,
        *,
        audio_format: str | None,
        sample_rate: int,
    ) -> tuple[bytes, str]:
        if isinstance(audio_data, (str, Path)):
            path = Path(audio_data)
            suffix = path.suffix.lower().lstrip(".")
            actual_format = audio_format or suffix or "wav"
            return path.read_bytes(), self._normalize_format(actual_format)

        if isinstance(audio_data, bytes):
            actual_format = self._normalize_format(audio_format or self.input_audio_format)
            if actual_format == "pcm_s16le":
                return self._wav_from_pcm_bytes(audio_data, sample_rate), "wav"
            return audio_data, actual_format

        return self._wav_from_samples(audio_data, sample_rate), "wav"

    @staticmethod
    def _normalize_format(audio_format: str) -> str:
        normalized = audio_format.lower().lstrip(".")
        if normalized in {"wave", "x-wav"}:
            return "wav"
        if normalized in {"mpeg", "mpga"}:
            return "mp3"
        return normalized

    @staticmethod
    def _wav_from_samples(audio_data: list | np.ndarray, sample_rate: int) -> bytes:
        samples = np.asarray(audio_data)
        if samples.dtype in {np.float32, np.float64}:
            samples = np.clip(samples, -1.0, 1.0)
            pcm = (samples * 32767).astype(np.int16)
        else:
            pcm = samples.astype(np.int16)
        return MimoASR._wav_from_pcm_bytes(pcm.tobytes(), sample_rate)

    @staticmethod
    def _wav_from_pcm_bytes(pcm_audio: bytes, sample_rate: int) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_audio)
        return buffer.getvalue()

    @staticmethod
    def _to_data_url(audio: bytes, audio_format: str) -> str:
        encoded = base64.b64encode(audio).decode("ascii")
        return f"data:audio/{audio_format};base64,{encoded}"

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("MiMo ASR response did not include choices[0].message") from e

        content = message.get("content") or message.get("reasoning_content") or ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    value = item.get("text") or item.get("content")
                    if isinstance(value, str):
                        parts.append(value)
            return "".join(parts)
        return str(content)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
