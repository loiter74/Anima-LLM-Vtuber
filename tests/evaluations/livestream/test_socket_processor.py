from __future__ import annotations

import asyncio

from animetta.services.bilibili import DanmakuMessage, ReplyCandidate
from animetta.services.bilibili.reply_admission import ReplyPriority
from evaluations.livestream.socket_processor import SocketIOFullStackProcessor


class FakeAsyncClient:
    def __init__(self) -> None:
        self.handlers = {}
        self.connected_url = None
        self.disconnected = False
        self.emitted_payload = None

    def on(self, event, handler) -> None:
        self.handlers[event] = handler

    async def connect(self, url) -> None:
        self.connected_url = url

    async def disconnect(self) -> None:
        self.disconnected = True

    async def emit(self, event, payload) -> None:
        assert event == "chat:text"
        self.emitted_payload = payload
        identity = {
            "message_id": payload["message_id"],
            "conversation_id": payload["conversation_id"],
            "task_id": payload["task_id"],
            "turn_id": payload["task_id"],
        }
        await self.handlers["chat:sentence"](
            {**identity, "text": "Aura 回复", "seq": 0, "lang": "zh"}
        )
        await self.handlers["chat:audio_with_expression"]({**identity, "audio_data": "AA=="})
        await self.handlers["chat:live2d_action"]({**identity, "type": "expression"})
        await self.handlers["chat:control"]({**identity, "signal": "conversation-end"})


class FakeStreamingAsyncClient(FakeAsyncClient):
    async def emit(self, event, payload) -> None:
        assert event == "chat:text"
        identity = {
            "message_id": payload["message_id"],
            "conversation_id": payload["conversation_id"],
            "task_id": payload["task_id"],
            "turn_id": payload["task_id"],
        }
        stream_id = "stream-1"
        await self.handlers["chat:sentence"](
            {**identity, "text": "Aura 流式回复", "seq": 0, "lang": "zh"}
        )
        await self.handlers["chat:audio_stream_start"](
            {
                **identity,
                "stream_id": stream_id,
                "format": "pcm_s16le",
                "sample_rate": 24_000,
                "channels": 1,
                "emotion": "happy",
            }
        )
        await self.handlers["chat:audio_stream_chunk"](
            {**identity, "stream_id": stream_id, "sequence": 0, "audio_data": "AA=="}
        )
        await self.handlers["chat:audio_stream_end"](
            {
                **identity,
                "stream_id": stream_id,
                "final_sequence": 0,
                "status": "completed",
            }
        )
        await self.handlers["chat:live2d_action"]({**identity, "type": "expression"})
        await self.handlers["chat:control"]({**identity, "signal": "conversation-end"})


class FakeControlBeforeStreamingAudioClient(FakeAsyncClient):
    async def emit(self, event, payload) -> None:
        assert event == "chat:text"
        identity = {
            "message_id": payload["message_id"],
            "conversation_id": payload["conversation_id"],
            "task_id": payload["task_id"],
            "turn_id": payload["task_id"],
        }
        await self.handlers["chat:sentence"](
            {**identity, "text": "Aura 延迟音频回复", "seq": 0, "lang": "zh"}
        )
        await self.handlers["chat:live2d_action"]({**identity, "type": "expression"})
        await self.handlers["chat:control"]({**identity, "signal": "conversation-end"})
        asyncio.create_task(self._send_delayed_audio(identity))

    async def _send_delayed_audio(self, identity) -> None:
        await asyncio.sleep(0)
        stream_id = "stream-delayed"
        await self.handlers["chat:audio_stream_start"](
            {
                **identity,
                "stream_id": stream_id,
                "format": "pcm_s16le",
                "sample_rate": 24_000,
                "channels": 1,
                "emotion": "neutral",
            }
        )
        await self.handlers["chat:audio_stream_chunk"](
            {**identity, "stream_id": stream_id, "sequence": 0, "audio_data": "AA=="}
        )
        await self.handlers["chat:audio_stream_end"](
            {
                **identity,
                "stream_id": stream_id,
                "final_sequence": 0,
                "status": "completed",
            }
        )


async def test_socket_processor_waits_for_llm_tts_subtitle_and_live2d_delivery() -> None:
    client = FakeAsyncClient()
    processor = SocketIOFullStackProcessor("http://localhost", client=client, timeout_seconds=1)
    candidate = ReplyCandidate(
        message=DanmakuMessage(text="你好？", user_name="viewer_0001"),
        priority=ReplyPriority.QUESTION,
        generation_id=1,
        admitted_at=0,
    )

    await processor.connect()
    reply = await processor.process(candidate)
    await processor.close()

    assert reply == "Aura 回复"
    assert client.connected_url == "http://localhost"
    assert client.disconnected is True
    assert client.emitted_payload["source"] == "livestream"
    assert client.emitted_payload["is_acceptance"] is True
    assert processor.evidence() == {
        "completed": 1,
        "sentence_deliveries": 1,
        "audio_deliveries": 1,
        "live2d_deliveries": 1,
        "control_completions": 1,
    }


async def test_socket_processor_counts_completed_pcm_stream_as_audio_delivery() -> None:
    client = FakeStreamingAsyncClient()
    processor = SocketIOFullStackProcessor("http://localhost", client=client, timeout_seconds=1)
    candidate = ReplyCandidate(
        message=DanmakuMessage(text="你好？", user_name="viewer_0001"),
        priority=ReplyPriority.QUESTION,
        generation_id=1,
        admitted_at=0,
    )

    await processor.connect()
    reply = await processor.process(candidate)
    await processor.close()

    assert reply == "Aura 流式回复"
    assert processor.evidence()["audio_deliveries"] == 1


async def test_socket_processor_waits_when_control_precedes_streaming_audio() -> None:
    client = FakeControlBeforeStreamingAudioClient()
    processor = SocketIOFullStackProcessor("http://localhost", client=client, timeout_seconds=1)
    candidate = ReplyCandidate(
        message=DanmakuMessage(text="音频稍后到吗？", user_name="viewer_0001"),
        priority=ReplyPriority.QUESTION,
        generation_id=1,
        admitted_at=0,
    )

    await processor.connect()
    reply = await processor.process(candidate)
    await processor.close()

    assert reply == "Aura 延迟音频回复"
    assert processor.evidence() == {
        "completed": 1,
        "sentence_deliveries": 1,
        "audio_deliveries": 1,
        "live2d_deliveries": 1,
        "control_completions": 1,
    }
