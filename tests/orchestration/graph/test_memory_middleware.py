from __future__ import annotations

from animetta.orchestration.graph.memory_middleware import MemoryMiddleware

"""Tests for MemoryMiddleware — memory injection before/after LLM."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestMemoryMiddleware:
    """Memory middleware handles graceful degradation."""

    @pytest.mark.asyncio
    async def test_before_call_without_memory_system(self):
        """Without memory system, returns base prompt unchanged."""

        mm = MemoryMiddleware(memory_system=None)
        enriched, metadata = await mm.before_llm_call(
            session_id="test",
            user_input="hello",
            base_prompt="You are a helpful assistant.",
        )
        assert enriched == "You are a helpful assistant."
        assert metadata is None

    @pytest.mark.asyncio
    async def test_after_call_without_memory_system(self):
        """Without memory system, after_llm_call does nothing."""

        mm = MemoryMiddleware(memory_system=None)
        await mm.after_llm_call(
            session_id="test",
            user_input="hello",
            agent_response="Hi there!",
        )
        # No exception = pass

    @pytest.mark.asyncio
    async def test_before_call_with_memory_system(self):
        """With memory system, enriches prompt with context."""

        mock_memory = MagicMock()
        mock_memory.retrieve_context = AsyncMock(return_value=[
            MagicMock(
                user_input="I like Python",
                agent_response="Python is great!",
                metadata={"oral_version": "user likes Python"},
            ),
        ])
        mock_memory.build_user_profile = AsyncMock(
            return_value=MagicMock(
                is_empty=lambda: True,
                format_for_prompt=lambda: "",
            )
        )

        mm = MemoryMiddleware(memory_system=mock_memory)
        enriched, metadata = await mm.before_llm_call(
            session_id="test",
            user_input="hello",
            base_prompt="You are helpful.",
        )
        assert enriched is not None
        assert "You are helpful" in enriched
        assert metadata is not None

    @pytest.mark.asyncio
    async def test_after_call_does_not_crash(self):
        """after_llm_call should not raise with valid input."""

        mm = MemoryMiddleware(memory_system=MagicMock())
        # after_llm_call is just a post-processing marker, doesn't store
        await mm.after_llm_call(
            session_id="test",
            user_input="hello",
            agent_response="Hi!",
        )
        # No exception = pass

    @pytest.mark.asyncio
    async def test_memory_error_does_not_crash(self):
        """Memory errors should not propagate — middleware degrades gracefully."""

        mock_memory = MagicMock()
        mock_memory.retrieve_context = AsyncMock(side_effect=Exception("DB down"))
        mock_memory.fuzzy = None  # No fuzzy store (prevents MagicMock auto-creation)

        mm = MemoryMiddleware(memory_system=mock_memory)
        enriched, metadata = await mm.before_llm_call(
            session_id="test",
            user_input="hello",
            base_prompt="You are helpful.",
        )
        # Should return base prompt unchanged on error
        assert enriched == "You are helpful."
