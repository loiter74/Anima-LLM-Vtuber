from __future__ import annotations

"""Tests for OpenAIStreamHandler — streaming buffer, chunk accumulation, completion detection."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.services.llm.stream_handler import OpenAIStreamHandler


@pytest.fixture
def mock_openai_llm():
    """Create a mock OpenAILLM instance."""
    llm = MagicMock()
    llm.model = "gpt-4"
    llm.temperature = 0.7
    llm.top_p = 0.93
    llm.max_tokens = 1024
    llm.history = []
    llm.client = MagicMock()
    llm._record_usage = MagicMock()
    llm._record_error = MagicMock()
    return llm


@pytest.fixture
def handler(mock_openai_llm):
    """Create an OpenAIStreamHandler with a mock LLM."""
    return OpenAIStreamHandler(mock_openai_llm)


class TestOpenAIStreamHandler:
    """Tests for OpenAIStreamHandler."""

    async def test_stream_yields_chunks(self, handler, mock_openai_llm):
        """Stream should yield content chunks from the API response."""
        # Mock the streaming response
        mock_chunk_1 = MagicMock()
        mock_chunk_1.choices = [MagicMock()]
        mock_chunk_1.choices[0].delta.content = "Hello"
        mock_chunk_1.usage = None

        mock_chunk_2 = MagicMock()
        mock_chunk_2.choices = [MagicMock()]
        mock_chunk_2.choices[0].delta.content = " world"
        mock_chunk_2.usage = None

        mock_response = AsyncMock()
        mock_response.__aiter__.return_value = [mock_chunk_1, mock_chunk_2]

        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai_llm._build_messages = MagicMock(return_value=[{"role": "user", "content": "hi"}])

        chunks = []
        async for chunk in handler.stream("hi"):
            chunks.append(chunk)

        assert chunks == ["Hello", " world"]
        assert len(mock_openai_llm.history) == 2  # user + assistant
        assert mock_openai_llm.history[-1]["content"] == "Hello world"

    async def test_stream_empty_response(self, handler, mock_openai_llm):
        """Stream should handle empty response gracefully."""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = None  # no content
        mock_chunk.usage = None

        mock_response = AsyncMock()
        mock_response.__aiter__.return_value = [mock_chunk]

        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai_llm._build_messages = MagicMock(return_value=[])

        chunks = []
        async for chunk in handler.stream("hi"):
            chunks.append(chunk)

        assert chunks == []

    async def test_stream_error_raises(self, handler, mock_openai_llm):
        """Stream should re-raise API errors after recording them."""
        mock_openai_llm.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API timeout")
        )
        mock_openai_llm._build_messages = MagicMock(return_value=[])

        with pytest.raises(Exception, match="API timeout"):
            async for chunk in handler.stream("hi"):
                pass  # pragma: no cover

        mock_openai_llm._record_error.assert_called_once()

    async def test_stream_system_prompt_override(self, handler, mock_openai_llm):
        """Stream should pass system_prompt kwarg through to _build_messages."""
        mock_response = AsyncMock()
        mock_response.__aiter__.return_value = []
        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        async for _ in handler.stream("hi", system_prompt="You are a cat."):
            pass

        mock_openai_llm._build_messages.assert_called_with(
            "hi", system_prompt="You are a cat."
        )

    async def test_stream_records_usage(self, handler, mock_openai_llm):
        """Stream should record usage metrics after completion."""
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "test"
        mock_chunk.usage = None

        mock_response = AsyncMock()
        mock_response.__aiter__.return_value = [mock_chunk]

        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai_llm._build_messages = MagicMock(return_value=[])

        async for _ in handler.stream("hello world"):
            pass

        assert mock_openai_llm._record_usage.called

    async def test_stream_passes_top_p_to_api(self, handler, mock_openai_llm):
        """Stream calls should pass top_p to keep streamed chat sampling lively."""
        mock_response = AsyncMock()
        mock_response.__aiter__.return_value = []
        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        mock_openai_llm._build_messages = MagicMock(return_value=[])

        async for _ in handler.stream("hi"):
            pass

        call_kwargs = mock_openai_llm.client.chat.completions.create.await_args.kwargs
        assert call_kwargs["top_p"] == 0.93
