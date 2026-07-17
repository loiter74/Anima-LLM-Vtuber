"""Direct, emotion-aware DashScope Qwen realtime TTS provider."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import wave
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlencode
from uuid import uuid4

from loguru import logger
from websockets.asyncio.client import connect as websocket_connect

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts.dashscope import DashScopeTTSConfig

from .emotion_instructions import all_emotion_instructions
from .interface import TTSInterface
from .remote_tts import RemoteTTSError


class DashScopeError(RemoteTTSError):
    """Sanitized DashScope realtime failure."""


class DashScopeProtocolError(DashScopeError):
    """DashScope returned an invalid realtime event."""


class DashScopeConnectionError(DashScopeError):
    """DashScope WebSocket connection failed."""


class WebSocketLike(Protocol):
    async def send(self, message: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...


class WebSocketConnector(Protocol):
    def __call__(
        self, url: str, headers: Mapping[str, str]
    ) -> AbstractAsyncContextManager[WebSocketLike]: ...


def _default_connector(
    url: str,
    headers: Mapping[str, str],
    *,
    open_timeout: float,
) -> AbstractAsyncContextManager[WebSocketLike]:
    connection = websocket_connect(
        url,
        additional_headers=dict(headers),
        open_timeout=open_timeout,
        close_timeout=5,
        max_size=None,
    )
    return cast(AbstractAsyncContextManager[WebSocketLike], connection)


@dataclass(slots=True)
class _HotSession:
    instruction: str
    socket: WebSocketLike
    connection: AbstractAsyncContextManager[WebSocketLike]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@ProviderRegistry.register_service("tts", "dashscope")
class DashScopeRealtimeTTS(TTSInterface):
    """Stream 24 kHz PCM over instruction-keyed reusable WebSockets."""

    supports_streaming = True
    supports_emotion_instructions = True
    provider_identity = "dashscope"
    _MAX_HOT_SESSIONS = 6

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "qwen3-tts-instruct-flash-realtime",
        voice: str = "Seren",
        base_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        response_format: str = "pcm",
        sample_rate: int = 24000,
        language_type: str = "Chinese",
        timeout_seconds: float = 20.0,
        connect_timeout_seconds: float = 5.0,
        connector: WebSocketConnector | None = None,
        uuid_factory: Callable[[], str] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("DashScope TTS requires DASHSCOPE_API_KEY")
        if response_format != "pcm" or sample_rate != 24000:
            raise ValueError("DashScope realtime streaming requires 24 kHz PCM")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.base_url = base_url.rstrip("?")
        self.response_format = response_format
        self._sample_rate = sample_rate
        self.language_type = language_type
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self._preload_retry_delay_seconds = 1.0
        self._session_close_timeout_seconds = 1.0
        self._max_request_seconds = max(60.0, timeout_seconds * 3)
        self._connector = connector or (
            lambda url, headers: _default_connector(
                url,
                headers,
                open_timeout=self.connect_timeout_seconds,
            )
        )
        self._uuid_factory = (lambda: str(uuid4())) if uuid_factory is None else uuid_factory
        self._sessions: dict[str, _HotSession] = {}
        self._sessions_lock = asyncio.Lock()
        self._closed = False

    @classmethod
    def from_config(cls, config: DashScopeTTSConfig, **kwargs: Any) -> DashScopeRealtimeTTS:
        return cls(
            api_key=config.api_key,
            model=config.model,
            voice=config.voice,
            base_url=config.base_url,
            response_format=config.response_format,
            sample_rate=config.sample_rate,
            language_type=config.language_type,
            timeout_seconds=config.timeout_seconds,
            connect_timeout_seconds=config.connect_timeout_seconds,
            connector=kwargs.get("connector"),
            uuid_factory=kwargs.get("uuid_factory"),
        )

    @property
    def resolved_identity(self) -> dict[str, str]:
        return {
            "type": "dashscope",
            "provider": self.provider_identity,
            "model": self.model,
            "voice": self.voice,
        }

    @property
    def audio_format(self) -> str:
        return "pcm_s16le"

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def preload(self) -> None:
        """Open all six emotion instruction sessions before the first chat turn."""

        for instruction in all_emotion_instructions():
            for attempt in range(2):
                try:
                    await self._session_for(instruction)
                    break
                except DashScopeError as exc:
                    if attempt == 1 or not exc.retryable:
                        raise
                    logger.warning("DashScope preload connection failed transiently; retrying once")
                    await asyncio.sleep(self._preload_retry_delay_seconds)

    async def synthesize_stream(
        self,
        text: str,
        *,
        instruction: str,
        emotion: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """Yield ordered PCM chunks while keeping the instruction session hot."""

        del emotion, kwargs
        if not text or not text.strip():
            return
        if not instruction or not instruction.strip():
            raise ValueError("DashScope realtime TTS requires an instruction")
        if self._closed:
            raise DashScopeConnectionError(
                "DashScope TTS is closed",
                category="unavailable",
                retryable=False,
            )

        session = await self._session_for(instruction)
        owns_request = False
        try:
            await session.lock.acquire()
            owns_request = True
            loop = asyncio.get_running_loop()
            request_deadline = loop.time() + self._max_request_seconds
            await self._send(
                session.socket,
                {
                    "event_id": self._uuid_factory(),
                    "type": "input_text_buffer.append",
                    "text": text,
                },
            )
            await self._send(
                session.socket,
                {
                    "event_id": self._uuid_factory(),
                    "type": "input_text_buffer.commit",
                },
            )

            yielded = False
            while True:
                remaining = request_deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError("DashScope request exceeded its total deadline")
                async with asyncio.timeout(min(self.timeout_seconds, remaining)):
                    event = await self._receive(session.socket)
                event_type = event.get("type")
                if event_type == "error":
                    raise self._remote_error(event)
                if event_type == "response.audio.delta":
                    chunk = self._decode_audio(event)
                    if chunk:
                        yielded = True
                        yield chunk
                elif event_type == "response.done":
                    response = event.get("response")
                    status = response.get("status") if isinstance(response, Mapping) else None
                    if status != "completed":
                        raise DashScopeProtocolError(
                            "DashScope response did not complete",
                            category="provider_error",
                            retryable=True,
                        )
                    break
                elif event_type == "session.finished":
                    raise DashScopeConnectionError(
                        "DashScope session closed during synthesis",
                        category="connection",
                        retryable=True,
                    )
            if not yielded:
                raise DashScopeProtocolError(
                    "DashScope response completed without audio",
                    category="empty_audio",
                    retryable=True,
                )
        except BaseException as exc:
            if owns_request:
                await self._discard_session(instruction, session)
            if isinstance(
                exc,
                (DashScopeError, asyncio.CancelledError, TimeoutError, GeneratorExit),
            ):
                raise
            raise DashScopeConnectionError(
                "DashScope realtime connection failed",
                category="connection",
                retryable=True,
            ) from exc
        finally:
            if owns_request:
                session.lock.release()

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        **kwargs: Any,
    ) -> bytes | str:
        """Collect one stream into a WAV for complete-audio compatibility."""

        instruction = str(kwargs.get("instruction") or "")
        chunks = [
            chunk
            async for chunk in self.synthesize_stream(
                text,
                instruction=instruction,
                emotion=kwargs.get("emotion"),
            )
        ]
        audio = self._wav_bytes(b"".join(chunks)) if chunks else b""
        if output_path is None:
            return audio
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return str(path)

    async def close(self) -> None:
        """Finish every hot session and close its WebSocket."""

        self._closed = True
        async with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await self._finish_session(session)

    async def _session_for(self, instruction: str) -> _HotSession:
        async with self._sessions_lock:
            existing = self._sessions.get(instruction)
            if existing is not None:
                return existing
            if len(self._sessions) >= self._MAX_HOT_SESSIONS:
                raise DashScopeConnectionError(
                    "DashScope emotion session pool is full",
                    category="busy",
                    retryable=True,
                )

            url = f"{self.base_url}?{urlencode({'model': self.model})}"
            connection = self._connector(url, self._headers())
            try:
                socket = await connection.__aenter__()
                async with asyncio.timeout(self.connect_timeout_seconds):
                    await self._expect(socket, "session.created")
                    await self._send(
                        socket,
                        {
                            "event_id": self._uuid_factory(),
                            "type": "session.update",
                            "session": {
                                "voice": self.voice,
                                "mode": "commit",
                                "language_type": self.language_type,
                                "response_format": self.response_format,
                                "sample_rate": self.sample_rate,
                                "instructions": instruction,
                                "optimize_instructions": True,
                            },
                        },
                    )
                    await self._expect(socket, "session.updated")
            except BaseException as exc:
                await connection.__aexit__(type(exc), exc, exc.__traceback__)
                if isinstance(exc, DashScopeError):
                    raise
                raise DashScopeConnectionError(
                    "DashScope WebSocket connection failed",
                    category="connection",
                    retryable=True,
                ) from exc

            session = _HotSession(instruction, socket, connection)
            self._sessions[instruction] = session
            return session

    async def _discard_session(self, instruction: str, session: _HotSession) -> None:
        async with self._sessions_lock:
            if self._sessions.get(instruction) is session:
                self._sessions.pop(instruction, None)
        try:
            async with asyncio.timeout(self._session_close_timeout_seconds):
                await session.connection.__aexit__(None, None, None)
        except (Exception, asyncio.CancelledError):
            logger.debug("DashScope failed session close was ignored")

    async def _finish_session(self, session: _HotSession) -> None:
        try:
            async with session.lock:
                await self._send(
                    session.socket,
                    {"event_id": self._uuid_factory(), "type": "session.finish"},
                )
                async with asyncio.timeout(self.connect_timeout_seconds):
                    while True:
                        event = await self._receive(session.socket)
                        if event.get("type") == "session.finished":
                            break
        except Exception:
            logger.debug("DashScope session finish acknowledgement unavailable")
        finally:
            try:
                await session.connection.__aexit__(None, None, None)
            except Exception:
                logger.debug("DashScope session close was ignored")

    async def _expect(self, socket: WebSocketLike, expected_type: str) -> None:
        event = await self._receive(socket)
        event_type = event.get("type")
        if event_type == "error":
            raise self._remote_error(event)
        if event_type != expected_type:
            raise DashScopeProtocolError(
                f"DashScope expected {expected_type}",
                category="provider_error",
                retryable=True,
            )

    @staticmethod
    async def _send(socket: WebSocketLike, event: Mapping[str, Any]) -> None:
        await socket.send(json.dumps(event, ensure_ascii=False, separators=(",", ":")))

    @staticmethod
    async def _receive(socket: WebSocketLike) -> dict[str, Any]:
        raw = await socket.recv()
        if not isinstance(raw, str):
            raise DashScopeProtocolError(
                "DashScope realtime event must be JSON",
                category="provider_error",
                retryable=True,
            )
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DashScopeProtocolError(
                "DashScope realtime event is invalid JSON",
                category="provider_error",
                retryable=True,
            ) from exc
        if not isinstance(event, dict):
            raise DashScopeProtocolError(
                "DashScope realtime event must be an object",
                category="provider_error",
                retryable=True,
            )
        return cast(dict[str, Any], event)

    @staticmethod
    def _decode_audio(event: Mapping[str, Any]) -> bytes:
        delta = event.get("delta")
        if not isinstance(delta, str):
            raise DashScopeProtocolError(
                "DashScope audio delta is missing",
                category="provider_error",
                retryable=True,
            )
        try:
            return base64.b64decode(delta, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DashScopeProtocolError(
                "DashScope audio delta is invalid",
                category="provider_error",
                retryable=True,
            ) from exc

    @staticmethod
    def _remote_error(event: Mapping[str, Any]) -> DashScopeError:
        error = event.get("error")
        code = (
            str(error.get("code") or "remote_error")
            if isinstance(error, Mapping)
            else "remote_error"
        )
        category = (
            "authentication"
            if code in {"invalid_api_key", "authentication_error"}
            else "provider_error"
        )
        return DashScopeError(
            f"DashScope realtime failed: {code}",
            category=category,
            retryable=category != "authentication",
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "user-agent": "animetta/0.1",
        }

    def _wav_bytes(self, pcm: bytes) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm)
        return buffer.getvalue()
