from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any

import pytest

from animetta.acceptance.tts_audition.clients import (
    CosyVoiceClient,
    ProtocolError,
    QwenRealtimeClient,
)
from animetta.acceptance.tts_audition.plan import build_audition_plan


class FakeHttpTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


class FakeWebSocket:
    def __init__(self, incoming: list[str | bytes]) -> None:
        self.incoming = iter(incoming)
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str | bytes) -> None:
        assert isinstance(message, str)
        self.sent.append(json.loads(message))

    async def recv(self) -> str | bytes:
        return next(self.incoming)


class FakeConnection(AbstractAsyncContextManager[FakeWebSocket]):
    def __init__(self, socket: FakeWebSocket) -> None:
        self.socket = socket

    async def __aenter__(self) -> FakeWebSocket:
        return self.socket

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


class FakeConnector:
    def __init__(self, socket: FakeWebSocket) -> None:
        self.socket = socket
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str]
    ) -> AbstractAsyncContextManager[FakeWebSocket]:
        self.calls.append((url, dict(headers)))
        return FakeConnection(self.socket)


def _ids(*values: str) -> Iterator[str]:
    yield from values


async def test_cosyvoice_voice_design_uses_beijing_contract_and_decodes_preview() -> None:
    candidate = build_audition_plan().candidates[0]
    preview = b"RIFF-preview"
    http = FakeHttpTransport(
        {
            "output": {
                "preview_audio": {
                    "data": base64.b64encode(preview).decode("ascii"),
                    "sample_rate": 24000,
                    "response_format": "wav",
                },
                "target_model": candidate.model,
                "voice_id": "cosyvoice-v3.5-flash-vd-animaa-123",
            },
            "usage": {"count": 1},
            "request_id": "request-design-a",
        }
    )
    client = CosyVoiceClient(
        api_key="secret", http=http, connector=FakeConnector(FakeWebSocket([]))
    )

    result = await client.create_designed_voice(
        candidate=candidate,
        prefix="animaa",
        preview_text="今晚不必急着回答，我会把时间留给你。",
    )

    assert result.voice_id == "cosyvoice-v3.5-flash-vd-animaa-123"
    assert result.preview_audio == preview
    assert result.request_id == "request-design-a"
    [call] = http.calls
    assert call["url"] == "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
    assert call["headers"]["Authorization"] == "Bearer secret"
    assert call["payload"] == {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": "cosyvoice-v3.5-flash",
            "voice_prompt": candidate.voice_design_prompt,
            "preview_text": "今晚不必急着回答，我会把时间留给你。",
            "prefix": "animaa",
            "language_hints": ["zh"],
        },
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }


async def test_cosyvoice_voice_design_accepts_legacy_response_bound_by_voice_id() -> None:
    candidate = build_audition_plan().candidates[0]
    preview = b"RIFF-preview"
    http = FakeHttpTransport(
        {
            "output": {
                "preview_audio": {
                    "data": base64.b64encode(preview).decode("ascii"),
                    "sample_rate": 24000,
                    "response_format": "wav",
                },
                "voice_id": "cosyvoice-v3.5-flash-vd-animaa-legacy",
            },
            "request_id": "request-design-legacy",
        }
    )
    client = CosyVoiceClient(
        api_key="secret", http=http, connector=FakeConnector(FakeWebSocket([]))
    )

    result = await client.create_designed_voice(
        candidate=candidate,
        prefix="animaa",
        preview_text="今晚不必急着回答，我会把时间留给你。",
    )

    assert result.target_model == candidate.model
    assert result.voice_id == "cosyvoice-v3.5-flash-vd-animaa-legacy"


async def test_cosyvoice_voice_design_rejects_legacy_response_for_other_model() -> None:
    candidate = build_audition_plan().candidates[0]
    http = FakeHttpTransport(
        {
            "output": {
                "preview_audio": {
                    "data": base64.b64encode(b"RIFF-preview").decode("ascii"),
                    "sample_rate": 24000,
                    "response_format": "wav",
                },
                "voice_id": "cosyvoice-v3.5-plus-vd-animaa-wrong",
            },
            "request_id": "request-design-wrong",
        }
    )
    client = CosyVoiceClient(
        api_key="secret", http=http, connector=FakeConnector(FakeWebSocket([]))
    )

    with pytest.raises(ProtocolError, match="does not match"):
        await client.create_designed_voice(
            candidate=candidate,
            prefix="animaa",
            preview_text="今晚不必急着回答，我会把时间留给你。",
        )


async def test_cosyvoice_session_sends_matching_task_events_and_collects_pcm() -> None:
    socket = FakeWebSocket(
        [
            json.dumps({"header": {"task_id": "task-a", "event": "task-started"}, "payload": {}}),
            b"\x01\x02",
            json.dumps(
                {
                    "header": {"task_id": "task-a", "event": "result-generated"},
                    "payload": {"output": {"sentence": {"index": 0}}},
                }
            ),
            b"\x03\x04",
            json.dumps(
                {
                    "header": {
                        "task_id": "task-a",
                        "event": "task-finished",
                        "attributes": {"request_uuid": "request-a"},
                    },
                    "payload": {"usage": {"characters": 12}},
                }
            ),
        ]
    )
    connector = FakeConnector(socket)
    client = CosyVoiceClient(
        api_key="secret",
        http=FakeHttpTransport({}),
        connector=connector,
        uuid_factory=lambda: "task-a",
    )

    async with client.open_session() as session:
        result = await session.synthesize(
            model="cosyvoice-v3.5-flash",
            voice="designed-voice-a",
            text="今晚不必急着回答。",
            instruction="整体冷静克制；保持自然平稳。",
        )

    assert result.audio_pcm == b"\x01\x02\x03\x04"
    assert result.request_id == "request-a"
    assert result.character_count == 12
    assert result.cold_connection is True
    [connection] = connector.calls
    assert connection[0] == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    assert connection[1]["Authorization"] == "Bearer secret"
    assert [message["header"]["action"] for message in socket.sent] == [
        "run-task",
        "continue-task",
        "finish-task",
    ]
    assert {message["header"]["task_id"] for message in socket.sent} == {"task-a"}
    run_parameters = socket.sent[0]["payload"]["parameters"]
    assert run_parameters == {
        "text_type": "PlainText",
        "voice": "designed-voice-a",
        "format": "pcm",
        "sample_rate": 24000,
        "volume": 50,
        "rate": 1.0,
        "pitch": 1.0,
        "instruction": "整体冷静克制；保持自然平稳。",
    }


async def test_qwen_realtime_sends_instruct_events_and_decodes_pcm() -> None:
    audio = b"\x10\x20\x30\x40"
    socket = FakeWebSocket(
        [
            json.dumps({"type": "session.created", "session": {"id": "session-a"}}),
            json.dumps({"type": "session.updated", "session": {"id": "session-a"}}),
            json.dumps(
                {"type": "response.audio.delta", "delta": base64.b64encode(audio).decode("ascii")}
            ),
            json.dumps(
                {
                    "type": "response.done",
                    "response": {
                        "id": "response-a",
                        "status": "completed",
                        "usage": {"characters": 16},
                    },
                }
            ),
            json.dumps({"type": "session.finished"}),
        ]
    )
    connector = FakeConnector(socket)
    event_ids = _ids("update-a", "append-a", "commit-a", "finish-a")
    client = QwenRealtimeClient(
        api_key="secret", connector=connector, uuid_factory=lambda: next(event_ids)
    )

    result = await client.synthesize(
        model="qwen3-tts-instruct-flash-realtime",
        voice="Vivian",
        text="事情比预想得顺利。",
        instruction="整体保持冷静、克制；只增加轻微明亮感。",
    )

    assert result.audio_pcm == audio
    assert result.request_id == "response-a"
    assert result.character_count == 16
    [connection] = connector.calls
    assert connection[0].endswith("?model=qwen3-tts-instruct-flash-realtime")
    assert connection[1]["Authorization"] == "Bearer secret"
    assert [message["type"] for message in socket.sent] == [
        "session.update",
        "input_text_buffer.append",
        "input_text_buffer.commit",
        "session.finish",
    ]
    assert socket.sent[0]["session"] == {
        "voice": "Vivian",
        "mode": "commit",
        "language_type": "Chinese",
        "response_format": "pcm",
        "sample_rate": 24000,
        "instructions": "整体保持冷静、克制；只增加轻微明亮感。",
        "optimize_instructions": True,
    }


async def test_qwen_realtime_rejects_malformed_audio_delta() -> None:
    socket = FakeWebSocket(
        [
            json.dumps({"type": "session.created", "session": {"id": "session-a"}}),
            json.dumps({"type": "session.updated", "session": {"id": "session-a"}}),
            json.dumps({"type": "response.audio.delta", "delta": "not-base64%%%"}),
        ]
    )
    event_ids = _ids("update-a", "append-a", "commit-a", "finish-a")
    client = QwenRealtimeClient(
        api_key="secret",
        connector=FakeConnector(socket),
        uuid_factory=lambda: next(event_ids),
    )

    with pytest.raises(ProtocolError, match="audio"):
        await client.synthesize(
            model="qwen3-tts-instruct-flash-realtime",
            voice="Seren",
            text="让我想一想。",
            instruction="保持克制并放慢语速。",
        )
