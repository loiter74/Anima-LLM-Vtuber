"""Strict client for an independently deployed TTS service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts.remote import RemoteTTSConfig

from .audio_validation import is_valid_audio_payload
from .interface import TTSInterface


class RemoteTTSError(RuntimeError):
    """Sanitized, typed remote TTS failure."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        request_id: str | None = None,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.request_id = request_id
        self.retryable = retryable
        self.status_code = status_code


class RemoteTTSAuthenticationError(RemoteTTSError):
    """The remote service rejected application credentials."""


class RemoteTTSIdentityMismatchError(RemoteTTSError):
    """Configured and resolved service identities differ."""


class RemoteTTSNotReadyError(RemoteTTSError):
    """The remote model dependency is not ready."""


class RemoteTTSTimeoutError(RemoteTTSError):
    """The remote operation exceeded its configured deadline."""


class RemoteTTSProtocolError(RemoteTTSError):
    """The remote response violated the versioned contract."""


class RemoteTTSUpstreamError(RemoteTTSError):
    """The remote service failed or is temporarily busy."""


@ProviderRegistry.register_service("tts", "remote")
class RemoteTTS(TTSInterface):
    """Remote speech client that never changes provider, model, or voice."""

    _CONTENT_TYPES_BY_FORMAT = {
        "wav": {"audio/wav", "audio/x-wav", "audio/wave"},
        "mp3": {"audio/mpeg"},
        "opus": {"audio/ogg", "audio/opus"},
    }
    _READINESS_CONTRACT = {"service": "qwen-tts", "api_version": "v1"}
    _CLIENT_ERROR_CATEGORIES = frozenset(
        {"invalid_request", "unsupported_identity", "request_rejected"}
    )
    _UPSTREAM_ERROR_CATEGORIES = frozenset(
        {"generation_failed", "invalid_audio", "model_unavailable", "not_ready", "timeout"}
    )
    _BUSY_RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        provider: str,
        model: str,
        voice: str,
        response_format: str,
        language: str | None,
        timeout_seconds: float,
        revision: str | None,
        quantization: str | None = None,
        runtime_commit: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.model = model
        self.voice = voice
        self.response_format = response_format
        self.language = language
        self.timeout_seconds = timeout_seconds
        self.revision = revision
        self.quantization = quantization
        self.runtime_commit = runtime_commit
        self._client = http_client
        self._resolved_identity: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, config: RemoteTTSConfig, **kwargs: Any) -> RemoteTTS:
        return cls(
            api_key=config.api_key,
            base_url=config.base_url,
            provider=config.provider,
            model=config.model,
            voice=config.voice,
            response_format=config.response_format,
            language=config.language,
            timeout_seconds=config.timeout_seconds,
            revision=config.revision or (config.worker.revision if config.worker else None),
            quantization=config.quantization,
            runtime_commit=config.runtime_commit,
            http_client=kwargs.get("http_client"),
        )

    @property
    def configured_identity(self) -> dict[str, str | None]:
        identity = {
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "voice": self.voice,
        }
        if self.quantization is not None:
            identity["quantization"] = self.quantization
        if self.runtime_commit is not None:
            identity["runtime_commit"] = self.runtime_commit
        return identity

    @property
    def resolved_identity(self) -> dict[str, Any] | None:
        return dict(self._resolved_identity) if self._resolved_identity else None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json, audio/*"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    async def check_readiness(self) -> dict[str, Any]:
        """Validate cached worker readiness and exact configured identity."""
        try:
            response = await self._get_client().get(
                f"{self.base_url}/ready",
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise RemoteTTSTimeoutError(
                "Remote TTS readiness timed out",
                category="timeout",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise RemoteTTSNotReadyError(
                "Remote TTS readiness request failed",
                category="connection",
                retryable=True,
            ) from exc

        if response.status_code in {401, 403}:
            raise RemoteTTSAuthenticationError(
                "Remote TTS authentication failed",
                category="authentication",
                retryable=False,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise RemoteTTSNotReadyError(
                "Remote TTS dependency is not ready",
                category="not_ready",
                retryable=response.status_code >= 429,
                status_code=response.status_code,
            )

        payload = self._json_object(response, operation="readiness")
        if payload.get("ready") is not True:
            raise RemoteTTSNotReadyError(
                "Remote TTS dependency is not ready",
                category="not_ready",
                retryable=True,
                status_code=response.status_code,
            )
        self._validate_readiness_contract(payload)
        self._validate_identity(payload, include_revision=True)
        self._resolved_identity = dict(payload)
        return dict(payload)

    async def preload(self) -> None:
        """Model-manager hook: readiness succeeds only after exact identity validation."""
        await self.check_readiness()

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        **kwargs: Any,
    ) -> bytes | str:
        """Synthesize audio and validate response correlation and identity."""
        if not text or not text.strip():
            if output_path is None:
                return b""
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")
            return str(path)

        actual_model = kwargs.get("model", self.model)
        actual_voice = kwargs.get("voice", self.voice)
        if actual_model != self.model:
            self._raise_identity_error("model", self.model, actual_model)
        if actual_voice != self.voice:
            self._raise_identity_error("voice", self.voice, actual_voice)

        request_id = str(kwargs.get("request_id") or uuid4())
        payload: dict[str, Any] = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": self.response_format,
            "request_id": request_id,
        }
        language = kwargs.get("language", self.language)
        if language:
            payload["language"] = language

        response = await self._post_speech_with_busy_retry(payload, request_id)

        self._raise_for_speech_status(response, request_id)
        self._validate_speech_response(response, request_id)
        audio = response.content

        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
            return str(path)
        return audio

    async def synthesize_stream(
        self,
        text: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """Stream authenticated PCM16 while validating the fixed worker identity."""
        if not text or not text.strip():
            return
        actual_model = kwargs.get("model", self.model)
        actual_voice = kwargs.get("voice", self.voice)
        if actual_model != self.model:
            self._raise_identity_error("model", self.model, actual_model)
        if actual_voice != self.voice:
            self._raise_identity_error("voice", self.voice, actual_voice)

        request_id = str(kwargs.get("request_id") or uuid4())
        payload: dict[str, Any] = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": self.response_format,
            "request_id": request_id,
            "stream": True,
        }
        language = kwargs.get("language", self.language)
        if language:
            payload["language"] = language

        retry_delays = self._BUSY_RETRY_DELAYS_SECONDS
        for attempt in range(len(retry_delays) + 1):
            try:
                async with self._get_client().stream(
                    "POST",
                    f"{self.base_url}/v1/audio/speech",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                ) as response:
                    if response.status_code == 429 and attempt < len(retry_delays):
                        await response.aread()
                        await asyncio.sleep(retry_delays[attempt])
                        continue
                    if response.status_code >= 400:
                        await response.aread()
                        self._raise_for_speech_status(response, request_id)
                    self._validate_stream_headers(response, request_id)
                    yielded = False
                    carry = b""
                    async for network_chunk in response.aiter_bytes():
                        data = carry + network_chunk
                        even_length = len(data) - (len(data) % 2)
                        if even_length:
                            yielded = True
                            yield data[:even_length]
                        carry = data[even_length:]
                    if carry or not yielded:
                        raise RemoteTTSProtocolError(
                            "Remote TTS stream contains invalid PCM audio",
                            category="invalid_audio",
                            request_id=request_id,
                            retryable=True,
                        )
                    return
            except httpx.TimeoutException as exc:
                raise RemoteTTSTimeoutError(
                    "Remote TTS streaming timed out",
                    category="timeout",
                    request_id=request_id,
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise RemoteTTSUpstreamError(
                    "Remote TTS streaming connection failed",
                    category="connection",
                    request_id=request_id,
                    retryable=True,
                ) from exc

        raise AssertionError("streaming busy retry loop must return")

    def _validate_stream_headers(
        self,
        response: httpx.Response,
        request_id: str,
    ) -> None:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "audio/pcm":
            raise RemoteTTSProtocolError(
                "Remote TTS stream has unsupported content type",
                category="invalid_audio",
                request_id=request_id,
                retryable=False,
            )
        if response.headers.get("x-animetta-audio-format") != "pcm_s16le":
            raise RemoteTTSProtocolError(
                "Remote TTS stream has incompatible audio format",
                category="incompatible_contract",
                request_id=request_id,
                retryable=False,
            )
        if response.headers.get("x-animetta-sample-rate") != "24000":
            raise RemoteTTSProtocolError(
                "Remote TTS stream has incompatible sample rate",
                category="incompatible_contract",
                request_id=request_id,
                retryable=False,
            )
        if response.headers.get("x-animetta-channels") != "1":
            raise RemoteTTSProtocolError(
                "Remote TTS stream has incompatible channel count",
                category="incompatible_contract",
                request_id=request_id,
                retryable=False,
            )
        self._validate_identity(
            {
                "provider": response.headers.get("x-animetta-provider"),
                "model": response.headers.get("x-animetta-model"),
                "voice": response.headers.get("x-animetta-voice"),
            },
            include_revision=False,
            request_id=request_id,
        )
        if response.headers.get("x-request-id") != request_id:
            raise RemoteTTSIdentityMismatchError(
                "Remote TTS response request ID mismatch",
                category="identity_mismatch",
                request_id=request_id,
            )

    async def _post_speech_with_busy_retry(
        self,
        payload: dict[str, Any],
        request_id: str,
    ) -> httpx.Response:
        """Retry only the worker's typed, retryable single-capacity response."""
        retry_delays = self._BUSY_RETRY_DELAYS_SECONDS
        for attempt in range(len(retry_delays) + 1):
            try:
                response = await self._get_client().post(
                    f"{self.base_url}/v1/audio/speech",
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                raise RemoteTTSTimeoutError(
                    "Remote TTS synthesis timed out",
                    category="timeout",
                    request_id=request_id,
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise RemoteTTSUpstreamError(
                    "Remote TTS connection failed",
                    category="connection",
                    request_id=request_id,
                    retryable=True,
                ) from exc

            if response.status_code != 429 or attempt == len(retry_delays):
                return response
            await asyncio.sleep(retry_delays[attempt])

        raise AssertionError("busy retry loop must return a response")

    def _raise_for_speech_status(self, response: httpx.Response, request_id: str) -> None:
        status = response.status_code
        if status < 400:
            return
        payload = self._optional_json_object(response)
        response_request_id = str(payload.get("request_id") or request_id)
        if status in {401, 403}:
            raise RemoteTTSAuthenticationError(
                "Remote TTS authentication failed",
                category="authentication",
                request_id=response_request_id,
                retryable=False,
                status_code=status,
            )
        category = self._normalized_error_category(status, payload.get("category"))
        error_type = RemoteTTSProtocolError if 400 <= status < 429 else RemoteTTSUpstreamError
        raise error_type(
            "Remote TTS request failed",
            category=category,
            request_id=response_request_id,
            retryable=status >= 429,
            status_code=status,
        )

    @classmethod
    def _normalized_error_category(cls, status: int, value: Any) -> str:
        """Map untrusted worker categories into a bounded public vocabulary."""
        supplied = value if isinstance(value, str) else None
        if status == 429:
            return "busy"
        if status >= 500:
            return supplied if supplied in cls._UPSTREAM_ERROR_CATEGORIES else "upstream_failure"
        return supplied if supplied in cls._CLIENT_ERROR_CATEGORIES else "request_rejected"

    @classmethod
    def _validate_readiness_contract(cls, payload: dict[str, Any]) -> None:
        for field, expected in cls._READINESS_CONTRACT.items():
            if payload.get(field) != expected:
                raise RemoteTTSProtocolError(
                    f"Remote TTS {field} contract mismatch",
                    category="incompatible_contract",
                    retryable=False,
                )

    def _validate_speech_response(self, response: httpx.Response, request_id: str) -> None:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        expected_content_types = self._CONTENT_TYPES_BY_FORMAT[self.response_format]
        if content_type not in expected_content_types:
            raise RemoteTTSProtocolError(
                "Remote TTS response has unsupported content type",
                category="invalid_audio",
                request_id=request_id,
            )
        if not response.content:
            raise RemoteTTSProtocolError(
                "Remote TTS response contains empty audio",
                category="invalid_audio",
                request_id=request_id,
            )
        identity = {
            "provider": response.headers.get("x-animetta-provider"),
            "model": response.headers.get("x-animetta-model"),
            "voice": response.headers.get("x-animetta-voice"),
        }
        self._validate_identity(identity, include_revision=False, request_id=request_id)
        response_request_id = response.headers.get("x-request-id")
        if response_request_id != request_id:
            raise RemoteTTSIdentityMismatchError(
                "Remote TTS response request ID mismatch",
                category="identity_mismatch",
                request_id=request_id,
            )
        if not is_valid_audio_payload(response.content, self.response_format):
            raise RemoteTTSProtocolError(
                f"Remote TTS response is not decodable {self.response_format.upper()} audio",
                category="invalid_audio",
                request_id=request_id,
            )

    def _validate_identity(
        self,
        identity: dict[str, Any],
        *,
        include_revision: bool,
        request_id: str | None = None,
    ) -> None:
        expected: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "voice": self.voice,
        }
        if include_revision and self.revision:
            expected["revision"] = self.revision
        if include_revision and self.quantization:
            expected["quantization"] = self.quantization
        if include_revision and self.runtime_commit:
            expected["runtime_commit"] = self.runtime_commit
        for field, expected_value in expected.items():
            actual_value = identity.get(field)
            if actual_value != expected_value:
                self._raise_identity_error(field, expected_value, actual_value, request_id)

    @staticmethod
    def _json_object(response: httpx.Response, *, operation: str) -> dict[str, Any]:
        payload = RemoteTTS._optional_json_object(response)
        if not payload:
            raise RemoteTTSProtocolError(
                f"Remote TTS {operation} response is not a JSON object",
                category="invalid_response",
            )
        return payload

    @staticmethod
    def _optional_json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _raise_identity_error(
        field: str,
        expected: Any,
        actual: Any,
        request_id: str | None = None,
    ) -> None:
        raise RemoteTTSIdentityMismatchError(
            f"Remote TTS {field} identity mismatch: expected={expected!r}, actual={actual!r}",
            category="identity_mismatch",
            request_id=request_id,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def audio_format(self) -> str:
        return self.response_format
