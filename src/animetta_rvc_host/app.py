"""Authenticated Starlette boundary for the host-local RVC engine."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

MAX_RVC_AUDIO_BYTES = 64 * 1024 * 1024


class RVCEngine(Protocol):
    async def preload(self) -> None: ...

    async def convert(self, audio: bytes, **kwargs: Any) -> bytes: ...

    async def close(self) -> None: ...


class SeparationEngine(Protocol):
    model: str

    async def preload(self) -> None: ...

    async def separate(self, audio: bytes) -> Path: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RVCServiceSettings:
    api_key: str
    provider: str
    model: str
    revision: str
    voice: str
    sample_rate: int
    index: str = ""
    index_revision: str = ""
    conversion_timeout_seconds: float = 1200.0
    separation_model: str = ""

    def __post_init__(self) -> None:
        values = (self.api_key, self.provider, self.model, self.revision, self.voice)
        if not all(value.strip() for value in values):
            raise ValueError("RVC service identity and API key must be non-empty")
        if self.sample_rate <= 0 or self.conversion_timeout_seconds <= 0:
            raise ValueError("RVC service numeric settings must be positive")
        if bool(self.index.strip()) != bool(self.index_revision.strip()):
            raise ValueError("RVC index identity fields must be configured together")

    def identity_fields(self) -> dict[str, str | int]:
        identity: dict[str, str | int] = {
            "provider": self.provider,
            "model": self.model,
            "revision": self.revision,
            "voice": self.voice,
            "sample_rate": self.sample_rate,
        }
        if self.index and self.index_revision:
            identity["index"] = self.index
            identity["index_revision"] = self.index_revision
        return identity


class RVCService:
    def __init__(
        self,
        settings: RVCServiceSettings,
        engine: RVCEngine,
        separator: SeparationEngine | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.separator = separator
        self._ready = False
        self._separation_ready = False

    async def preload(self) -> None:
        await self.engine.preload()
        if self.separator is not None:
            await self.separator.preload()
            self._separation_ready = True
        self._ready = True

    def authorized(self, request: Request) -> bool:
        expected = f"Bearer {self.settings.api_key}"
        return hmac.compare_digest(request.headers.get("authorization", ""), expected)

    def identity(self) -> dict[str, Any]:
        return {
            "ready": self._ready,
            "separation_ready": self._separation_ready,
            "separation_model": self.settings.separation_model,
            "service": "rvc",
            "api_version": "v1",
            **self.settings.identity_fields(),
        }

    async def convert(self, payload: dict[str, Any]) -> Response:
        request_id = str(payload.get("request_id") or uuid4())
        if not self._ready:
            return JSONResponse({"category": "not_ready", "request_id": request_id}, 503)
        if payload.get("model") != self.settings.model:
            return JSONResponse({"category": "model_mismatch", "request_id": request_id}, 422)
        encoded = payload.get("audio_base64")
        if not isinstance(encoded, str) or not encoded:
            return JSONResponse({"category": "invalid_audio", "request_id": request_id}, 422)
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return JSONResponse({"category": "invalid_audio", "request_id": request_id}, 422)
        if len(audio) <= 44 or len(audio) > MAX_RVC_AUDIO_BYTES:
            return JSONResponse({"category": "invalid_audio", "request_id": request_id}, 422)

        kwargs = {
            "f0_method": str(payload.get("f0_method") or "rmvpe"),
            "f0_up_key": int(payload.get("f0_up_key") or 0),
            "index_rate": float(payload.get("index_rate") or 0.0),
            "filter_radius": int(payload.get("filter_radius") or 3),
            "rms_mix_rate": float(payload.get("rms_mix_rate") or 0.5),
            "protect": float(payload.get("protect") or 0.5),
        }
        try:
            converted = await asyncio.wait_for(
                self.engine.convert(audio, **kwargs),
                timeout=self.settings.conversion_timeout_seconds,
            )
        except TimeoutError:
            return JSONResponse({"category": "timeout", "request_id": request_id}, 504)
        except (OSError, RuntimeError, ValueError):
            return JSONResponse({"category": "conversion_failed", "request_id": request_id}, 500)
        if len(converted) <= 44:
            return JSONResponse({"category": "empty_audio", "request_id": request_id}, 500)
        headers = {
            "X-RVC-Provider": self.settings.provider,
            "X-RVC-Model": self.settings.model,
            "X-RVC-Revision": self.settings.revision,
            "X-RVC-Voice": self.settings.voice,
            "X-RVC-Request-ID": request_id,
        }
        return Response(converted, media_type="audio/wav", headers=headers)

    async def separate(self, audio: bytes, *, model: str, request_id: str) -> Response:
        if not self._ready or not self._separation_ready or self.separator is None:
            return JSONResponse({"category": "not_ready", "request_id": request_id}, 503)
        if model != self.settings.separation_model:
            return JSONResponse({"category": "model_mismatch", "request_id": request_id}, 422)
        if len(audio) <= 44 or len(audio) > 128 * 1024 * 1024:
            return JSONResponse({"category": "invalid_audio", "request_id": request_id}, 422)
        try:
            archive_path = await self.separator.separate(audio)
        except TimeoutError:
            return JSONResponse({"category": "timeout", "request_id": request_id}, 504)
        except (OSError, RuntimeError, ValueError):
            return JSONResponse({"category": "separation_failed", "request_id": request_id}, 500)
        if not archive_path.is_file() or archive_path.stat().st_size <= 22:
            return JSONResponse({"category": "empty_audio", "request_id": request_id}, 500)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename="stems.zip",
            headers={
                "X-Separation-Model": self.settings.separation_model,
                "X-RVC-Request-ID": request_id,
            },
            background=BackgroundTask(shutil.rmtree, archive_path.parent, ignore_errors=True),
        )

    async def close(self) -> None:
        if self.separator is not None:
            await self.separator.close()
            self._separation_ready = False
        await self.engine.close()
        self._ready = False


def create_app(service: RVCService) -> Starlette:
    @asynccontextmanager
    async def lifespan(_app: Starlette):
        await service.preload()
        try:
            yield
        finally:
            await service.close()

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "rvc", "api_version": "v1"})

    async def ready(request: Request) -> Response:
        if not service.authorized(request):
            return JSONResponse({"category": "unauthorized"}, 401)
        return JSONResponse(service.identity(), 200 if service._ready else 503)

    async def convert(request: Request) -> Response:
        if not service.authorized(request):
            return JSONResponse({"category": "unauthorized"}, 401)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"category": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return JSONResponse({"category": "invalid_json"}, 400)
        return await service.convert(payload)

    async def separate(request: Request) -> Response:
        if not service.authorized(request):
            return JSONResponse({"category": "unauthorized"}, 401)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > 128 * 1024 * 1024:
                    return JSONResponse({"category": "invalid_audio"}, 422)
            except ValueError:
                return JSONResponse({"category": "invalid_audio"}, 422)
        return await service.separate(
            await request.body(),
            model=request.headers.get("x-separation-model", ""),
            request_id=request.headers.get("x-request-id", "") or str(uuid4()),
        )

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/ready", ready),
            Route("/v1/identity", ready),
            Route("/v1/convert", convert, methods=["POST"]),
            Route("/v1/separate", separate, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
