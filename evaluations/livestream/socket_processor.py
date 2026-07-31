"""Socket.IO adapter that drives the running LLM/TTS/subtitle/Live2D pipeline."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import socketio

from animetta.services.bilibili import ReplyCandidate


class SocketIOFullStackProcessor:
    """Submit admitted replies to a live Animetta server and await delivery."""

    def __init__(
        self,
        server_url: str,
        *,
        client: Any | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.server_url = server_url
        self.client = client or socketio.AsyncClient(reconnection=True)
        self.timeout_seconds = timeout_seconds
        self._conversation_id = str(uuid4())
        self._pending: dict[str, dict[str, Any]] = {}
        self._completed = 0
        self._sentence_tasks: set[str] = set()
        self._audio_tasks: set[str] = set()
        self._audio_streams: dict[str, dict[str, Any]] = {}
        self._live2d_tasks: set[str] = set()
        self._control_tasks: set[str] = set()
        self._connected = False
        self.client.on("chat:sentence", self._on_sentence)
        self.client.on("chat:audio_with_expression", self._on_audio)
        self.client.on("chat:audio_stream_start", self._on_audio_stream_start)
        self.client.on("chat:audio_stream_chunk", self._on_audio_stream_chunk)
        self.client.on("chat:audio_stream_end", self._on_audio_stream_end)
        self.client.on("chat:live2d_action", self._on_live2d)
        self.client.on("chat:control", self._on_control)
        self.client.on("system:error", self._on_error)

    async def connect(self) -> None:
        await self.client.connect(self.server_url)
        self._connected = True

    async def close(self) -> None:
        if self._connected:
            await self.client.disconnect()
            self._connected = False
        for state in self._pending.values():
            future = state["future"]
            if not future.done():
                future.set_exception(RuntimeError("full-stack processor closed"))
        self._pending.clear()
        self._audio_streams.clear()

    async def process(self, candidate: ReplyCandidate) -> str:
        if not self._connected:
            raise RuntimeError("full-stack Socket.IO processor is not connected")
        task_id = str(uuid4())
        message_id = str(uuid4())
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[task_id] = {"future": future, "sentences": []}
        await self.client.emit(
            "chat:text",
            {
                "text": candidate.message.text,
                "message_id": message_id,
                "conversation_id": self._conversation_id,
                "task_id": task_id,
                "user_id": candidate.message.user_name or "anonymous",
                "from_name": candidate.message.user_name or "viewer",
                "source": "livestream",
                "is_acceptance": True,
            },
        )
        try:
            reply = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        finally:
            self._pending.pop(task_id, None)
            stale_stream_ids = [
                stream_id
                for stream_id, stream in self._audio_streams.items()
                if stream["task_id"] == task_id
            ]
            for stream_id in stale_stream_ids:
                self._audio_streams.pop(stream_id, None)
        self._completed += 1
        return reply

    def evidence(self) -> dict[str, int]:
        return {
            "completed": self._completed,
            "sentence_deliveries": len(self._sentence_tasks),
            "audio_deliveries": len(self._audio_tasks),
            "live2d_deliveries": len(self._live2d_tasks),
            "control_completions": len(self._control_tasks),
        }

    async def _on_sentence(self, payload: dict[str, Any]) -> None:
        task_id = str(payload.get("task_id", ""))
        state = self._pending.get(task_id)
        if state is None:
            return
        state["sentences"].append(str(payload.get("text", "")))
        self._sentence_tasks.add(task_id)
        self._maybe_complete(task_id)

    async def _on_audio(self, payload: dict[str, Any]) -> None:
        task_id = str(payload.get("task_id", ""))
        if task_id in self._pending:
            self._audio_tasks.add(task_id)
            self._maybe_complete(task_id)

    async def _on_audio_stream_start(self, payload: dict[str, Any]) -> None:
        task_id = str(payload.get("task_id", ""))
        stream_id = str(payload.get("stream_id", ""))
        if task_id not in self._pending or not stream_id:
            return
        self._audio_streams[stream_id] = {
            "task_id": task_id,
            "next_sequence": 0,
            "chunk_count": 0,
            "valid": True,
        }

    async def _on_audio_stream_chunk(self, payload: dict[str, Any]) -> None:
        stream_id = str(payload.get("stream_id", ""))
        stream = self._audio_streams.get(stream_id)
        if stream is None or str(payload.get("task_id", "")) != stream["task_id"]:
            return
        if payload.get("sequence") != stream["next_sequence"] or not payload.get("audio_data"):
            stream["valid"] = False
            return
        stream["next_sequence"] += 1
        stream["chunk_count"] += 1

    async def _on_audio_stream_end(self, payload: dict[str, Any]) -> None:
        stream_id = str(payload.get("stream_id", ""))
        stream = self._audio_streams.pop(stream_id, None)
        if stream is None or str(payload.get("task_id", "")) != stream["task_id"]:
            return
        completed = (
            payload.get("status") == "completed"
            and stream["valid"]
            and stream["chunk_count"] > 0
            and payload.get("final_sequence") == stream["next_sequence"] - 1
        )
        if completed and stream["task_id"] in self._pending:
            self._audio_tasks.add(stream["task_id"])
            self._maybe_complete(stream["task_id"])

    async def _on_live2d(self, payload: dict[str, Any]) -> None:
        task_id = str(payload.get("task_id", ""))
        if task_id in self._pending:
            self._live2d_tasks.add(task_id)
            self._maybe_complete(task_id)

    async def _on_control(self, payload: dict[str, Any]) -> None:
        if payload.get("signal") != "conversation-end":
            return
        task_id = str(payload.get("task_id", ""))
        state = self._pending.get(task_id)
        if state is None:
            return
        self._control_tasks.add(task_id)
        self._maybe_complete(task_id)

    def _maybe_complete(self, task_id: str) -> None:
        state = self._pending.get(task_id)
        if state is None:
            return
        delivered = (
            task_id in self._sentence_tasks
            and task_id in self._audio_tasks
            and task_id in self._live2d_tasks
            and task_id in self._control_tasks
        )
        future = state["future"]
        if delivered and not future.done():
            future.set_result("".join(state["sentences"]))

    async def _on_error(self, payload: dict[str, Any]) -> None:
        task_id = str(payload.get("task_id", ""))
        state = self._pending.get(task_id)
        if state is None:
            return
        future = state["future"]
        if not future.done():
            future.set_exception(RuntimeError(str(payload.get("message", "full-stack error"))))
