from __future__ import annotations

"""Xiaomi MiMo-backed VAD implementation."""

import base64
import inspect
import io
import wave
from typing import Any

import numpy as np
from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.vad.mimo import MimoVADConfig

from .interface import VADInterface, VADResult, VADState


@ProviderRegistry.register_service("vad", "mimo")
class MimoVAD(VADInterface):
    """Local endpointing VAD with optional MiMo ASR confirmation at speech end."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "mimo-v2.5-asr",
        base_url: str = "https://api.xiaomimimo.com/v1",
        language: str = "auto",
        audio_format: str = "wav",
        sample_rate: int = 16000,
        db_threshold: float = -35.0,
        min_speech_duration: int = 2,
        min_silence_duration: int = 8,
        confirm_with_asr: bool = True,
        timeout: float = 15.0,
        http_client: Any | None = None,
    ) -> None:
        if confirm_with_asr and not api_key:
            raise ValueError("MiMo VAD requires MIMO_API_KEY or VAD_API_KEY")

        self.api_key = api_key
        self.model = model
        self.base_url = self._resolve_base_url(api_key, base_url).rstrip("/")
        self.language = language
        self.audio_format = audio_format
        self.sample_rate = sample_rate
        self.db_threshold = db_threshold
        self.min_speech_duration = min_speech_duration
        self.min_silence_duration = min_silence_duration
        self.confirm_with_asr = confirm_with_asr
        self.timeout = timeout
        self._client = http_client

        self.state = VADState.IDLE
        self.speech_frames = 0
        self.silence_frames = 0
        self.audio_buffer = bytearray()
        self.pre_buffer: list[bytes] = []
        self.pre_buffer_max = 10

        logger.info(
            "MiMo VAD initialized: confirm_with_asr={}, db_threshold={}, sample_rate={}",
            confirm_with_asr,
            db_threshold,
            sample_rate,
        )

    @classmethod
    def from_config(cls, config: MimoVADConfig, **kwargs) -> MimoVAD:
        """Create instance from configuration."""
        return cls(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            language=config.language,
            audio_format=config.audio_format,
            sample_rate=config.sample_rate,
            db_threshold=config.db_threshold,
            min_speech_duration=config.min_speech_duration,
            min_silence_duration=config.min_silence_duration,
            confirm_with_asr=config.confirm_with_asr,
            timeout=config.timeout,
        )

    def detect_speech(self, audio_data: list | np.ndarray) -> VADResult:
        """Detect speech activity in an audio chunk."""
        audio_np = self._to_float32(audio_data)
        chunk_bytes = self._to_pcm_bytes(audio_np)
        is_loud = self._calculate_db(audio_np) > self.db_threshold

        if self.state == VADState.IDLE:
            self.pre_buffer.append(chunk_bytes)
            if len(self.pre_buffer) > self.pre_buffer_max:
                self.pre_buffer.pop(0)

            if is_loud:
                self.speech_frames += 1
                if self.speech_frames >= self.min_speech_duration:
                    self.state = VADState.ACTIVE
                    self.speech_frames = 0
                    self.silence_frames = 0
                    self.audio_buffer.extend(chunk_bytes)
                    return VADResult(
                        is_speech_start=True,
                        state=VADState.ACTIVE,
                        speech_detected=True,
                        metadata={"provider": "mimo"},
                    )
            else:
                self.speech_frames = 0

        elif self.state == VADState.ACTIVE:
            self.audio_buffer.extend(chunk_bytes)

            if is_loud:
                self.silence_frames = 0
            else:
                self.silence_frames += 1
                if self.silence_frames >= self.min_silence_duration:
                    audio = b"".join(self.pre_buffer) + bytes(self.audio_buffer)
                    metadata: dict[str, Any] = {"provider": "mimo"}
                    speech_detected = self._confirm_completed_speech(audio, metadata)
                    self._clear_buffers()
                    self.state = VADState.IDLE
                    return VADResult(
                        audio_data=audio,
                        is_speech_end=True,
                        state=VADState.IDLE,
                        speech_detected=speech_detected,
                        metadata=metadata,
                    )

        return VADResult(
            state=self.state,
            speech_detected=self.state == VADState.ACTIVE,
            metadata={"provider": "mimo"},
        )

    def reset(self) -> None:
        """Reset VAD state."""
        self.state = VADState.IDLE
        self.speech_frames = 0
        self.silence_frames = 0
        self._clear_buffers()
        logger.debug("MiMo VAD has been reset")

    def get_current_state(self) -> VADState:
        """Get current state."""
        return self.state

    async def close(self) -> None:
        """Close the HTTP client if this instance owns one."""
        self.reset()
        if self._client is None:
            return

        close = getattr(self._client, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
        else:
            aclose = getattr(self._client, "aclose", None)
            if callable(aclose):
                result = aclose()
                if inspect.isawaitable(result):
                    await result
        self._client = None

    def _clear_buffers(self) -> None:
        self.audio_buffer.clear()
        self.pre_buffer.clear()

    @staticmethod
    def _to_float32(audio_data: list | np.ndarray) -> np.ndarray:
        audio_np = np.asarray(audio_data, dtype=np.float32)
        if audio_np.size and np.max(np.abs(audio_np)) > 1.0:
            audio_np = audio_np / 32767.0
        return np.clip(audio_np, -1.0, 1.0)

    @staticmethod
    def _to_pcm_bytes(audio_np: np.ndarray) -> bytes:
        if not audio_np.size:
            return b""
        return (audio_np * 32767).astype(np.int16).tobytes()

    @staticmethod
    def _calculate_db(audio_np: np.ndarray) -> float:
        if not audio_np.size:
            return -float("inf")
        rms = float(np.sqrt(np.mean(np.square(audio_np))))
        return 20 * np.log10(rms + 1e-7) if rms > 0 else -float("inf")

    def _confirm_completed_speech(self, pcm_audio: bytes, metadata: dict[str, Any]) -> bool:
        if not self.confirm_with_asr:
            metadata["asr_confirmed"] = False
            return True

        try:
            text = self._transcribe_with_mimo(pcm_audio)
        except Exception as e:
            metadata["asr_error"] = type(e).__name__
            logger.warning("MiMo VAD ASR confirmation failed, preserving speech segment: {}", e)
            return True

        normalized = text.strip()
        metadata["asr_confirmed"] = True
        metadata["asr_text_len"] = len(normalized)
        return bool(normalized)

    def _transcribe_with_mimo(self, pcm_audio: bytes) -> str:
        if not self.api_key:
            raise ValueError("MiMo VAD requires MIMO_API_KEY or VAD_API_KEY")

        response = self._get_client().post(
            "/chat/completions",
            headers=self._headers(),
            json=self._build_payload(pcm_audio),
        )
        try:
            response.raise_for_status()
        except Exception as e:
            body = getattr(response, "text", "")
            status_code = getattr(response, "status_code", "unknown")
            raise RuntimeError(
                f"MiMo VAD ASR request failed: status={status_code}, body={body[:500]}"
            ) from e
        return self._extract_text(response.json())

    def _get_client(self):
        if self._client is None:
            try:
                import httpx
            except ImportError as e:
                raise ImportError("httpx is required for MiMo VAD") from e

            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
            logger.info("MiMo VAD HTTP client initialized (base_url={})", self.base_url)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "api-key": self.api_key or "",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _resolve_base_url(api_key: str | None, base_url: str) -> str:
        if api_key and api_key.startswith("tp-") and base_url.rstrip("/") == "https://api.xiaomimimo.com/v1":
            return "https://token-plan-cn.xiaomimimo.com/v1"
        return base_url

    def _build_payload(self, pcm_audio: bytes) -> dict[str, Any]:
        audio_data = self._encode_audio(pcm_audio)
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_data,
                            },
                        }
                    ],
                }
            ],
            "asr_options": {"language": self.language},
            "stream": False,
        }

    def _encode_audio(self, pcm_audio: bytes) -> str:
        wav_bytes = self._pcm_to_wav(pcm_audio)
        encoded = base64.b64encode(wav_bytes).decode("ascii")
        return f"data:audio/wav;base64,{encoded}"

    def _pcm_to_wav(self, pcm_audio: bytes) -> bytes:
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.sample_rate)
                wav.writeframes(pcm_audio)
            return buffer.getvalue()

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("MiMo VAD ASR response did not include choices[0].message") from e

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
