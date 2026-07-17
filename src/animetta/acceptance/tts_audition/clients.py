"""Strict, dependency-injected DashScope clients for the audition."""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol, cast
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect as websocket_connect

from animetta.acceptance.tts_audition.models import (
    AuditionCandidate,
    CandidateProvider,
    SynthesisResult,
    VoiceDesignResult,
)

VOICE_DESIGN_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
COSYVOICE_WEBSOCKET_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
QWEN_REALTIME_WEBSOCKET_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


class AuditionClientError(RuntimeError):
    """Base error safe to surface without provider response bodies or credentials."""


class ProtocolError(AuditionClientError):
    """Raised when a provider message violates the documented protocol."""


class RemoteAPIError(AuditionClientError):
    """Raised for a sanitized remote API failure."""


class JsonHttpTransport(Protocol):
    """Injectable JSON POST boundary."""

    async def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class WebSocketLike(Protocol):
    """Minimal WebSocket surface used by both provider clients."""

    async def send(self, message: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...


class WebSocketConnector(Protocol):
    """Callable returning an async WebSocket context manager."""

    def __call__(
        self, url: str, headers: Mapping[str, str]
    ) -> AbstractAsyncContextManager[WebSocketLike]: ...


class HttpxJsonTransport:
    """Default HTTP transport with sanitized failure reporting."""

    async def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                decoded = response.json()
        except httpx.HTTPStatusError as exc:
            raise RemoteAPIError(
                f"DashScope HTTP request failed with status {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RemoteAPIError("DashScope HTTP request failed") from exc
        if not isinstance(decoded, dict):
            raise ProtocolError("DashScope HTTP response must be a JSON object")
        return cast(dict[str, Any], decoded)


def default_websocket_connector(
    url: str, headers: Mapping[str, str]
) -> AbstractAsyncContextManager[WebSocketLike]:
    """Open a WebSocket using the repository's declared websockets dependency."""

    connection = websocket_connect(
        url,
        additional_headers=dict(headers),
        open_timeout=10,
        close_timeout=5,
        max_size=None,
    )
    return cast(AbstractAsyncContextManager[WebSocketLike], connection)


class CosyVoiceClient:
    """CosyVoice voice-design HTTP client and reusable synthesis connection."""

    def __init__(
        self,
        *,
        api_key: str,
        http: JsonHttpTransport | None = None,
        connector: WebSocketConnector = default_websocket_connector,
        uuid_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_key = api_key
        self._http = HttpxJsonTransport() if http is None else http
        self._connector = connector
        self._uuid_factory = (lambda: str(uuid4())) if uuid_factory is None else uuid_factory
        self._clock = clock

    async def create_designed_voice(
        self,
        *,
        candidate: AuditionCandidate,
        prefix: str,
        preview_text: str,
    ) -> VoiceDesignResult:
        """Create one original CosyVoice identity and decode its WAV preview."""

        if candidate.provider is not CandidateProvider.COSYVOICE:
            raise ValueError("candidate must use CosyVoice")
        if not candidate.voice_design_prompt:
            raise ValueError("CosyVoice candidate requires a voice design prompt")
        if not prefix.isalnum() or len(prefix) > 10:
            raise ValueError("voice prefix must be 1-10 ASCII letters or digits")
        if not preview_text or len(preview_text) > 200:
            raise ValueError("preview_text must contain 1-200 characters")
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": candidate.model,
                "voice_prompt": candidate.voice_design_prompt,
                "preview_text": preview_text,
                "prefix": prefix,
                "language_hints": ["zh"],
            },
            "parameters": {"sample_rate": 24000, "response_format": "wav"},
        }
        response = await self._http.post_json(
            url=VOICE_DESIGN_URL,
            headers=self._headers(),
            payload=payload,
            timeout_seconds=60,
        )
        return _parse_voice_design_response(response, expected_model=candidate.model)

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[CosyVoiceSession]:
        """Open one reusable connection so later candidate samples are warm tasks."""

        connection_started_at = self._clock()
        try:
            async with self._connector(COSYVOICE_WEBSOCKET_URL, self._headers()) as socket:
                connected_at = self._clock()
                yield CosyVoiceSession(
                    socket=socket,
                    uuid_factory=self._uuid_factory,
                    clock=self._clock,
                    connection_started_at=connection_started_at,
                    connected_at=connected_at,
                )
        except AuditionClientError:
            raise
        except Exception as exc:
            raise RemoteAPIError("CosyVoice WebSocket request failed") from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "user-agent": "animetta-tts-audition/1"}


class CosyVoiceSession:
    """One reusable CosyVoice WebSocket connection with task-level correlation."""

    def __init__(
        self,
        *,
        socket: WebSocketLike,
        uuid_factory: Callable[[], str],
        clock: Callable[[], float],
        connection_started_at: float,
        connected_at: float,
    ) -> None:
        self._socket = socket
        self._uuid_factory = uuid_factory
        self._clock = clock
        self._connection_started_at = connection_started_at
        self._connected_at = connected_at
        self._completed_tasks = 0

    async def synthesize(
        self,
        *,
        model: str,
        voice: str,
        text: str,
        instruction: str,
    ) -> SynthesisResult:
        """Run one correlated task and collect its ordered PCM frames."""

        if not text:
            raise ValueError("text must not be empty")
        if _cosy_instruction_weight(instruction) > 100:
            raise ValueError("CosyVoice instruction exceeds the documented 100-unit limit")
        task_id = self._uuid_factory()
        task_started_at = self._clock()
        is_cold = self._completed_tasks == 0
        measurement_started_at = self._connection_started_at if is_cold else task_started_at
        await self._send(
            {
                "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
                "payload": {
                    "task_group": "audio",
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "model": model,
                    "parameters": {
                        "text_type": "PlainText",
                        "voice": voice,
                        "format": "pcm",
                        "sample_rate": 24000,
                        "volume": 50,
                        "rate": 1.0,
                        "pitch": 1.0,
                        "instruction": instruction,
                    },
                    "input": {},
                },
            }
        )
        await self._wait_for_task_started(task_id)
        await self._send(
            {
                "header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"},
                "payload": {"input": {"text": text}},
            }
        )
        await self._send(
            {
                "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
                "payload": {"input": {}},
            }
        )

        chunks: list[bytes] = []
        first_packet_at: float | None = None
        request_id = task_id
        character_count = len(text)
        while True:
            raw = await self._socket.recv()
            if isinstance(raw, bytes):
                if raw:
                    if first_packet_at is None:
                        first_packet_at = self._clock()
                    chunks.append(raw)
                continue
            event = _decode_json_object(raw, "CosyVoice")
            header = _require_mapping(event, "header", "CosyVoice")
            _require_matching_task_id(header, task_id)
            event_type = header.get("event")
            if event_type in {"task-failed", "error"}:
                raise RemoteAPIError(f"CosyVoice task failed: {_safe_error_code(event)}")
            if event_type == "task-finished":
                attributes = header.get("attributes")
                if isinstance(attributes, Mapping) and attributes.get("request_uuid"):
                    request_id = str(attributes["request_uuid"])
                payload = event.get("payload")
                if isinstance(payload, Mapping):
                    usage = payload.get("usage")
                    if isinstance(usage, Mapping) and isinstance(usage.get("characters"), int):
                        character_count = int(usage["characters"])
                break

        completed_at = self._clock()
        if first_packet_at is None or not chunks:
            raise ProtocolError("CosyVoice task finished without audio")
        self._completed_tasks += 1
        return SynthesisResult(
            audio_pcm=b"".join(chunks),
            request_id=request_id,
            character_count=character_count,
            connection_seconds=(self._connected_at - self._connection_started_at)
            if is_cold
            else 0.0,
            first_packet_seconds=first_packet_at - measurement_started_at,
            total_seconds=completed_at - measurement_started_at,
            cold_connection=is_cold,
        )

    async def _wait_for_task_started(self, task_id: str) -> None:
        while True:
            raw = await self._socket.recv()
            if isinstance(raw, bytes):
                raise ProtocolError("CosyVoice sent audio before task-started")
            event = _decode_json_object(raw, "CosyVoice")
            header = _require_mapping(event, "header", "CosyVoice")
            _require_matching_task_id(header, task_id)
            event_type = header.get("event")
            if event_type == "task-started":
                return
            if event_type in {"task-failed", "error"}:
                raise RemoteAPIError(f"CosyVoice task failed: {_safe_error_code(event)}")
            raise ProtocolError(f"Unexpected CosyVoice event before task start: {event_type!s}")

    async def _send(self, event: Mapping[str, Any]) -> None:
        await self._socket.send(json.dumps(event, ensure_ascii=False, separators=(",", ":")))


class QwenRealtimeClient:
    """One-shot Qwen3-TTS Instruct Realtime synthesis client."""

    def __init__(
        self,
        *,
        api_key: str,
        connector: WebSocketConnector = default_websocket_connector,
        uuid_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_key = api_key
        self._connector = connector
        self._uuid_factory = (lambda: str(uuid4())) if uuid_factory is None else uuid_factory
        self._clock = clock

    async def synthesize(
        self,
        *,
        model: str,
        voice: str,
        text: str,
        instruction: str,
    ) -> SynthesisResult:
        """Synthesize one emotion-specific utterance over a fresh Qwen session."""

        if not text:
            raise ValueError("text must not be empty")
        connection_started_at = self._clock()
        url = f"{QWEN_REALTIME_WEBSOCKET_URL}?{urlencode({'model': model})}"
        try:
            async with self._connector(url, self._headers()) as socket:
                connected_at = self._clock()
                await _wait_for_qwen_event(socket, "session.created")
                await _send_qwen(
                    socket,
                    {
                        "event_id": self._uuid_factory(),
                        "type": "session.update",
                        "session": {
                            "voice": voice,
                            "mode": "commit",
                            "language_type": "Chinese",
                            "response_format": "pcm",
                            "sample_rate": 24000,
                            "instructions": instruction,
                            "optimize_instructions": True,
                        },
                    },
                )
                await _wait_for_qwen_event(socket, "session.updated")
                await _send_qwen(
                    socket,
                    {
                        "event_id": self._uuid_factory(),
                        "type": "input_text_buffer.append",
                        "text": text,
                    },
                )
                await _send_qwen(
                    socket,
                    {"event_id": self._uuid_factory(), "type": "input_text_buffer.commit"},
                )
                await _send_qwen(
                    socket,
                    {"event_id": self._uuid_factory(), "type": "session.finish"},
                )

                chunks: list[bytes] = []
                first_packet_at: float | None = None
                response_done = False
                request_id = ""
                character_count = len(text)
                while True:
                    raw = await socket.recv()
                    if isinstance(raw, bytes):
                        raise ProtocolError("Qwen realtime must return JSON audio events")
                    event = _decode_json_object(raw, "Qwen realtime")
                    event_type = event.get("type")
                    if event_type == "error":
                        raise RemoteAPIError(f"Qwen realtime failed: {_safe_error_code(event)}")
                    if event_type == "response.audio.delta":
                        chunk = _decode_qwen_audio(event)
                        if chunk:
                            if first_packet_at is None:
                                first_packet_at = self._clock()
                            chunks.append(chunk)
                    elif event_type == "response.done":
                        response = _require_mapping(event, "response", "Qwen realtime")
                        status = response.get("status")
                        if status != "completed":
                            raise RemoteAPIError(
                                f"Qwen realtime response ended with status {status!s}"
                            )
                        request_id = str(response.get("id", ""))
                        usage = response.get("usage")
                        if isinstance(usage, Mapping) and isinstance(usage.get("characters"), int):
                            character_count = int(usage["characters"])
                        response_done = True
                    elif event_type == "session.finished":
                        break
                completed_at = self._clock()
        except AuditionClientError:
            raise
        except Exception as exc:
            raise RemoteAPIError("Qwen realtime WebSocket request failed") from exc

        if not response_done:
            raise ProtocolError("Qwen realtime session finished without response.done")
        if first_packet_at is None or not chunks:
            raise ProtocolError("Qwen realtime response finished without audio")
        return SynthesisResult(
            audio_pcm=b"".join(chunks),
            request_id=request_id,
            character_count=character_count,
            connection_seconds=connected_at - connection_started_at,
            first_packet_seconds=first_packet_at - connection_started_at,
            total_seconds=completed_at - connection_started_at,
            cold_connection=True,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "user-agent": "animetta-tts-audition/1"}


def _parse_voice_design_response(
    response: Mapping[str, Any], *, expected_model: str
) -> VoiceDesignResult:
    output = _require_mapping(response, "output", "voice design")
    preview = _require_mapping(output, "preview_audio", "voice design")
    voice_id = str(output.get("voice_id", ""))
    reported_target_model = str(output.get("target_model", ""))
    target_model = reported_target_model or expected_model
    if not reported_target_model and not voice_id.startswith(f"{expected_model}-vd-"):
        raise ProtocolError("Voice design target_model does not match the candidate model")
    if target_model != expected_model:
        raise ProtocolError("Voice design target_model does not match the candidate model")
    request_id = str(response.get("request_id", ""))
    data = preview.get("data")
    if not voice_id or not request_id or not isinstance(data, str):
        raise ProtocolError(
            "Voice design response is missing voice_id, request_id, or preview audio"
        )
    try:
        preview_audio = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("Voice design preview audio is not valid base64") from exc
    sample_rate = preview.get("sample_rate")
    response_format = preview.get("response_format")
    if sample_rate != 24000 or response_format != "wav" or not preview_audio:
        raise ProtocolError("Voice design preview must be a non-empty 24 kHz WAV")
    return VoiceDesignResult(
        voice_id=voice_id,
        preview_audio=preview_audio,
        sample_rate=sample_rate,
        response_format=response_format,
        target_model=target_model,
        request_id=request_id,
    )


async def _wait_for_qwen_event(socket: WebSocketLike, expected_type: str) -> dict[str, Any]:
    raw = await socket.recv()
    if isinstance(raw, bytes):
        raise ProtocolError(f"Qwen realtime sent binary data before {expected_type}")
    event = _decode_json_object(raw, "Qwen realtime")
    event_type = event.get("type")
    if event_type == "error":
        raise RemoteAPIError(f"Qwen realtime failed: {_safe_error_code(event)}")
    if event_type != expected_type:
        raise ProtocolError(f"Expected Qwen {expected_type}, received {event_type!s}")
    return event


async def _send_qwen(socket: WebSocketLike, event: Mapping[str, Any]) -> None:
    await socket.send(json.dumps(event, ensure_ascii=False, separators=(",", ":")))


def _decode_qwen_audio(event: Mapping[str, Any]) -> bytes:
    delta = event.get("delta")
    if not isinstance(delta, str):
        raise ProtocolError("Qwen audio delta must contain base64 audio")
    try:
        return base64.b64decode(delta, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("Qwen audio delta is not valid base64 audio") from exc


def _decode_json_object(raw: str, provider: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"{provider} returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ProtocolError(f"{provider} event must be a JSON object")
    return cast(dict[str, Any], decoded)


def _require_mapping(value: Mapping[str, Any], key: str, provider: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise ProtocolError(f"{provider} response is missing {key}")
    return nested


def _require_matching_task_id(header: Mapping[str, Any], expected_task_id: str) -> None:
    if header.get("task_id") != expected_task_id:
        raise ProtocolError("CosyVoice event task_id does not match the active task")


def _safe_error_code(event: Mapping[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, Mapping) and error.get("code"):
        return str(error["code"])
    header = event.get("header")
    if isinstance(header, Mapping):
        return str(header.get("error_code") or header.get("event") or "remote_error")
    return "remote_error"


def _cosy_instruction_weight(instruction: str) -> int:
    return sum(2 if "\u4e00" <= character <= "\u9fff" else 1 for character in instruction)
