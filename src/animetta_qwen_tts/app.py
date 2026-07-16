"""Versioned Starlette boundary for the independently deployed Qwen worker."""

from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from loguru import logger
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from animetta.services.tts.audio_validation import is_valid_audio_payload


class QwenEngine(Protocol):
    async def preload(self) -> None: ...

    async def synthesize(self, text: str, **_kwargs: Any) -> bytes | str: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class QwenServiceSettings:
    """Sanitized service identity, authentication, and capacity settings."""

    api_key: str
    provider: str
    model: str
    revision: str
    voice: str
    language: str = "Chinese"
    response_format: str = "wav"
    sample_rate: int = 24000
    synthesis_timeout_seconds: float = 20.0
    capacity_wait_seconds: float = 0.05
    max_concurrency: int = 1
    max_new_tokens: int = 48
    warmup_enabled: bool = True
    warmup_text: str = "你好，我是爱丽丝。"
    warmup_max_new_tokens: int = 48

    def __post_init__(self) -> None:
        required = {
            "api_key": self.api_key,
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "voice": self.voice,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing Qwen service setting(s): {', '.join(missing)}")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.max_new_tokens < 1:
            raise ValueError("Qwen service codec token limit must be positive")
        if self.synthesis_timeout_seconds <= 0 or self.capacity_wait_seconds <= 0:
            raise ValueError("Qwen service timeouts must be positive")
        if self.warmup_enabled and not self.warmup_text.strip():
            raise ValueError("Qwen service warmup text must be non-empty")
        if self.warmup_max_new_tokens < 1:
            raise ValueError("Qwen service warmup token limit must be positive")


class QwenTTSService:
    """Own model readiness and serialize/bound GPU synthesis work."""

    def __init__(self, settings: QwenServiceSettings, engine: QwenEngine) -> None:
        self.settings = settings
        self.engine = engine
        self._capacity = asyncio.Semaphore(settings.max_concurrency)
        self._preload_lock = asyncio.Lock()
        self._ready = False
        self._readiness_category = "not_ready"
        self._closed = False
        self._background_synthesis: set[asyncio.Task[bytes | str]] = set()

    async def preload(self) -> None:
        """Preload the model and Alice prompt exactly once before readiness."""
        async with self._preload_lock:
            if self._ready:
                return
            try:
                await self.engine.preload()
                if self.settings.warmup_enabled:
                    warmup = await self.engine.synthesize(
                        self.settings.warmup_text,
                        language=self.settings.language,
                        max_new_tokens=self.settings.warmup_max_new_tokens,
                    )
                    warmup_audio = self._read_audio(warmup)
                    if not is_valid_audio_payload(
                        warmup_audio,
                        self.settings.response_format,
                    ):
                        raise RuntimeError("Qwen TTS warmup did not generate valid audio")
            except Exception:
                self._readiness_category = "preload_failed"
                logger.warning("Qwen TTS preload failed: category=preload_failed")
                raise
            self._ready = True
            self._readiness_category = "ready"
            logger.info(
                "Qwen TTS ready: provider={}, model={}, revision={}, voice={}",
                self.settings.provider,
                self.settings.model,
                self.settings.revision,
                self.settings.voice,
            )

    def identity(self) -> dict[str, Any]:
        if not self._ready:
            return {
                "ready": False,
                "service": "qwen-tts",
                "api_version": "v1",
                "category": self._readiness_category,
            }
        return {
            "ready": True,
            "service": "qwen-tts",
            "api_version": "v1",
            "provider": self.settings.provider,
            "model": self.settings.model,
            "revision": self.settings.revision,
            "voice": self.settings.voice,
            "sample_rate": self.settings.sample_rate,
        }

    def authorized(self, request: Request) -> bool:
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {self.settings.api_key}"
        return hmac.compare_digest(supplied, expected)

    async def synthesize(self, payload: dict[str, Any]) -> Response:
        request_id = str(payload.get("request_id") or uuid4())
        if not self._ready:
            return JSONResponse(
                {"category": "not_ready", "request_id": request_id},
                status_code=503,
            )

        expected = {
            "model": self.settings.model,
            "voice": self.settings.voice,
            "language": self.settings.language,
            "response_format": self.settings.response_format,
        }
        for field, expected_value in expected.items():
            actual_value = payload.get(field, expected_value if field == "language" else None)
            if actual_value != expected_value:
                return self._unsupported(field, request_id)
        text = payload.get("input")
        if not isinstance(text, str) or not text.strip():
            return self._unsupported("input", request_id)

        acquired = False
        try:
            await asyncio.wait_for(
                self._capacity.acquire(),
                timeout=self.settings.capacity_wait_seconds,
            )
            acquired = True
        except TimeoutError:
            return JSONResponse(
                {"category": "busy", "request_id": request_id},
                status_code=429,
            )

        deferred_release = False
        synthesis_task = asyncio.create_task(
            self.engine.synthesize(
                text,
                language=self.settings.language,
                max_new_tokens=self.settings.max_new_tokens,
            )
        )
        try:
            result = await asyncio.wait_for(
                asyncio.shield(synthesis_task),
                timeout=self.settings.synthesis_timeout_seconds,
            )
        except TimeoutError:
            deferred_release = True
            self._defer_capacity_release(synthesis_task)
            logger.warning("Qwen TTS synthesis degraded: category=timeout")
            return JSONResponse(
                {"category": "timeout", "request_id": request_id},
                status_code=504,
            )
        except asyncio.CancelledError:
            deferred_release = True
            self._defer_capacity_release(synthesis_task)
            logger.info(
                "Qwen TTS request cancelled; GPU capacity remains reserved "
                "until inference completes"
            )
            raise
        except Exception:
            logger.warning("Qwen TTS synthesis degraded: category=generation_failed")
            return JSONResponse(
                {"category": "generation_failed", "request_id": request_id},
                status_code=502,
            )
        finally:
            if acquired and not deferred_release:
                self._capacity.release()

        audio = self._read_audio(result)
        if not is_valid_audio_payload(audio, self.settings.response_format):
            return JSONResponse(
                {"category": "invalid_audio", "request_id": request_id},
                status_code=502,
            )
        return Response(
            audio,
            media_type=self._media_type(),
            headers={
                "x-animetta-provider": self.settings.provider,
                "x-animetta-model": self.settings.model,
                "x-animetta-voice": self.settings.voice,
                "x-request-id": request_id,
            },
        )

    @staticmethod
    def _unsupported(field: str, request_id: str) -> JSONResponse:
        return JSONResponse(
            {
                "category": "unsupported_identity",
                "field": field,
                "request_id": request_id,
            },
            status_code=422,
        )

    @staticmethod
    def _read_audio(result: bytes | str) -> bytes:
        if isinstance(result, bytes):
            return result
        try:
            return Path(result).read_bytes()
        except (OSError, TypeError):
            return b""

    def _media_type(self) -> str:
        return {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "opus": "audio/opus",
        }.get(self.settings.response_format, "application/octet-stream")

    def _defer_capacity_release(self, task: asyncio.Task[bytes | str]) -> None:
        """Track detached GPU work until it is safe to admit another request."""
        self._background_synthesis.add(task)
        task.add_done_callback(self._finish_deferred_synthesis)

    def _finish_deferred_synthesis(
        self,
        task: asyncio.Task[bytes | str],
    ) -> None:
        """Release GPU capacity only after non-cancellable worker work is terminal."""
        self._background_synthesis.discard(task)
        if not task.cancelled():
            task.exception()
        self._capacity.release()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._ready = False
        self._readiness_category = "closed"
        await self.engine.close()
        if self._background_synthesis:
            await asyncio.gather(*tuple(self._background_synthesis), return_exceptions=True)


def _default_service() -> QwenTTSService:
    """Build the worker lazily from the production manifest."""
    from animetta.config.manifest import load_remote_tts_worker_config
    from animetta.config.providers.tts.remote import RemoteTTSConfig
    from animetta.services.tts.qwen3_tts import Qwen3TTSTTS

    remote = load_remote_tts_worker_config()
    if not isinstance(remote, RemoteTTSConfig) or remote.worker is None:
        raise RuntimeError("Production TTS must declare a remote worker configuration")
    worker = remote.worker
    engine = Qwen3TTSTTS(
        model=remote.model,
        revision=worker.revision,
        speaker=remote.voice,
        device=worker.device,
        dtype=worker.dtype,
        language=worker.language,
        max_new_tokens=worker.max_new_tokens,
        top_p=worker.top_p,
        temperature=worker.temperature,
        repetition_penalty=worker.repetition_penalty,
        use_flash_attn=worker.use_flash_attn,
        ref_audio_path=worker.ref_audio_path,
        ref_text=worker.ref_text,
        x_vector_only=worker.x_vector_only,
    )
    return QwenTTSService(
        QwenServiceSettings(
            api_key=remote.api_key or "",
            provider=remote.provider,
            model=remote.model,
            revision=worker.revision,
            voice=remote.voice,
            language=worker.language,
            response_format=remote.response_format,
            synthesis_timeout_seconds=remote.timeout_seconds,
            max_new_tokens=worker.max_new_tokens,
            warmup_max_new_tokens=worker.max_new_tokens,
        ),
        engine,
    )


def create_app(
    *,
    service: QwenTTSService | None = None,
    preload_on_startup: bool = True,
) -> Starlette:
    """Create the standalone ASGI service without loading a model on import."""
    active_service = service or _default_service()

    @asynccontextmanager
    async def lifespan(app: Starlette):
        if preload_on_startup:
            await active_service.preload()
        try:
            yield
        finally:
            await active_service.close()

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "qwen-tts", "api_version": "v1"})

    def require_auth(request: Request) -> JSONResponse | None:
        if active_service.authorized(request):
            return None
        return JSONResponse({"category": "authentication"}, status_code=401)

    async def ready(request: Request) -> JSONResponse:
        denied = require_auth(request)
        if denied is not None:
            return denied
        identity = active_service.identity()
        return JSONResponse(identity, status_code=200 if identity["ready"] else 503)

    async def speech(request: Request) -> Response:
        denied = require_auth(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"category": "invalid_request"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"category": "invalid_request"}, status_code=400)
        return await active_service.synthesize(payload)

    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/ready", ready),
            Route("/v1/identity", ready),
            Route("/v1/audio/speech", speech, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
    app.state.qwen_tts_service = active_service
    return app
