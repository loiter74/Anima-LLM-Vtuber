from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.system import RecallResult
from animetta.orchestration.graph.memory_middleware import MemoryMiddleware


def _atom(content: str, *, scope: str = "community") -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        summary=None,
        scope=SimpleNamespace(value=scope),
        confidence=0.8,
        salience=0.7,
        origin={"channel": "bilibili"},
    )


class TestMemoryMiddleware:
    """Memory recall is bounded and always fails open for the live path."""

    @pytest.mark.asyncio
    async def test_before_call_without_memory_system(self):
        mm = MemoryMiddleware(memory_system=None)
        enriched, metadata = await mm.before_llm_call(
            session_id="transport-1",
            user_input="hello",
            base_prompt="You are a helpful assistant.",
        )
        assert enriched == "You are a helpful assistant."
        assert metadata is None

    @pytest.mark.asyncio
    async def test_after_call_without_memory_system(self):
        mm = MemoryMiddleware(memory_system=None)
        await mm.after_llm_call(
            session_id="transport-1",
            user_input="hello",
            agent_response="Hi there!",
        )

    @pytest.mark.asyncio
    async def test_structured_recall_passes_stable_context_and_budgets_items(self):
        context = MemoryContext(
            actor_id="bilibili:42",
            conversation_id="conversation-7",
            stream_id="live-9",
            channel="bilibili",
            connection_id="socket-a",
        )
        memory = MagicMock()
        memory.recall = AsyncMock(return_value=RecallResult(
            atoms=[_atom("one", scope="viewer"), _atom("two"), _atom("three")],
            metadata={"revision": 12},
        ))

        mm = MemoryMiddleware(memory_system=memory, max_items=2, max_prompt_chars=500)
        prompt, metadata = await mm.recall_structured(
            session_id="socket-a",
            user_input="remember me",
            context=context,
        )

        assert "one" in prompt and "two" in prompt and "three" not in prompt
        assert metadata == {
            "revision": 12,
            "candidate_count": 3,
            "atom_count": 2,
            "prompt_chars": len(prompt),
            "truncated": True,
            "degraded": False,
        }
        memory.recall.assert_awaited_once()
        kwargs = memory.recall.await_args.kwargs
        assert kwargs["context"] is context
        assert kwargs["limit"] == 2
        assert kwargs["session_id"] == "socket-a"

    @pytest.mark.asyncio
    async def test_structured_recall_enforces_prompt_character_budget(self):
        memory = MagicMock()
        memory.recall = AsyncMock(return_value=RecallResult(
            atoms=[_atom("x" * 200)],
            profile={"preference": "y" * 200},
            memes=[_atom("z" * 200, scope="community")],
        ))

        mm = MemoryMiddleware(memory_system=memory, max_prompt_chars=80)
        prompt, metadata = await mm.recall_structured(
            session_id="socket-a",
            user_input="hello",
        )

        assert len(prompt) <= 80
        assert metadata["prompt_chars"] == len(prompt)
        assert metadata["truncated"] is True

    @pytest.mark.asyncio
    async def test_recall_timeout_degrades_without_blocking_live_path(self):
        async def slow_recall(**_: object) -> RecallResult:
            await asyncio.sleep(0.05)
            return RecallResult()

        memory = MagicMock()
        memory.recall = AsyncMock(side_effect=slow_recall)
        mm = MemoryMiddleware(memory_system=memory, recall_timeout_ms=5)

        prompt, metadata = await mm.recall_structured(
            session_id="socket-a",
            user_input="hello",
        )

        assert prompt == ""
        assert metadata["degraded"] is True
        assert metadata["reason"] == "deadline_exceeded"
        assert metadata["deadline_ms"] == 5

    @pytest.mark.asyncio
    async def test_memory_error_does_not_crash(self):
        memory = MagicMock()
        memory.recall = AsyncMock(side_effect=RuntimeError("DB down"))
        mm = MemoryMiddleware(memory_system=memory)

        enriched, metadata = await mm.before_llm_call(
            session_id="transport-1",
            user_input="hello",
            base_prompt="You are helpful.",
        )

        assert enriched == "You are helpful."
        assert metadata is not None
        assert metadata["degraded"] is True
        assert metadata["reason"] == "recall_error"

    @pytest.mark.asyncio
    async def test_after_call_does_not_store(self):
        memory = MagicMock()
        mm = MemoryMiddleware(memory_system=memory)
        await mm.after_llm_call(
            session_id="transport-1",
            user_input="hello",
            agent_response="Hi!",
        )
        memory.encode.assert_not_called()
