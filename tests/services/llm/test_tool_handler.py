from __future__ import annotations

"""Tests for OpenAIToolHandler — tool call parsing, tool result formatting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.core.tools import tool

from animetta.services.llm.tool_handler import OpenAIToolHandler


@pytest.fixture
def mock_openai_llm():
    """Create a mock OpenAILLM instance."""
    llm = MagicMock()
    llm.model = "gpt-4"
    llm.temperature = 0.7
    llm.max_tokens = 1024
    llm.history = []
    llm.client = MagicMock()
    llm._record_usage = MagicMock()
    llm._record_error = MagicMock()
    return llm


@pytest.fixture
def handler(mock_openai_llm):
    """Create an OpenAIToolHandler with a mock LLM."""
    return OpenAIToolHandler(mock_openai_llm)


@tool
def fake_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Sunny in {city}"


@tool
def fake_calculator(expression: str) -> str:
    """Calculate an expression."""
    return "42"


class TestOpenAIToolHandler:
    """Tests for OpenAIToolHandler."""

    def test_convert_tools_to_openai(self, handler):
        """_convert_tools_to_openai should produce OpenAI-compatible tool definitions."""
        tools = [fake_weather, fake_calculator]
        result = handler._convert_tools_to_openai(tools)

        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "fake_weather"
        assert "city" in result[0]["function"]["parameters"]["properties"]

    def test_convert_tools_prefers_pydantic_v2_model_json_schema(self, handler):
        """_convert_tools_to_openai should avoid deprecated Pydantic V2 .schema()."""
        class ArgsSchema:
            @staticmethod
            def model_json_schema():
                return {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                }

            @staticmethod
            def schema():
                raise AssertionError(".schema() should not be called")

        tool_obj = MagicMock()
        tool_obj.name = "search"
        tool_obj.description = "Search"
        tool_obj.args_schema = ArgsSchema()

        result = handler._convert_tools_to_openai([tool_obj])

        assert result[0]["function"]["parameters"]["required"] == ["query"]

    def test_convert_tools_empty(self, handler):
        """_convert_tools_to_openai should return empty list for no tools."""
        assert handler._convert_tools_to_openai([]) == []

    def test_build_langchain_messages_system(self, handler):
        """_build_langchain_messages should include system prompt."""
        result = handler._build_langchain_messages(
            langchain_history=[],
            system_prompt="You are a helpful assistant.",
            user_input="Hello",
        )
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."
        assert result[-1]["role"] == "user"
        assert result[-1]["content"] == "Hello"

    def test_build_langchain_messages_history(self, handler):
        """_build_langchain_messages should convert LangChain message history."""
        history = [
            HumanMessage(content="What's the weather?"),
            AIMessage(content="Let me check."),
        ]
        result = handler._build_langchain_messages(
            langchain_history=history,
            system_prompt=None,
            user_input="In Paris",
        )

        # 2 history + latest user = 3 (no system prompt since system_prompt=None)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "What's the weather?"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "Let me check."
        assert result[2]["role"] == "user"
        assert result[2]["content"] == "In Paris"

    def test_build_langchain_messages_tool_calls(self, handler):
        """_build_langchain_messages should handle AIMessage with tool_calls."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "get_weather", "args": {"city": "Paris"}}],
        )
        history = [
            HumanMessage(content="Weather in Paris?"),
            ai_msg,
            ToolMessage(content='{"temp": 25}', tool_call_id="call_1"),
        ]
        result = handler._build_langchain_messages(
            langchain_history=history,
            system_prompt=None,
            user_input="Thanks",
        )

        tool_msg = [m for m in result if m["role"] == "tool"]
        assert len(tool_msg) == 1
        assert tool_msg[0]["tool_call_id"] == "call_1"

        ai_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(ai_msgs) >= 1
        assert "tool_calls" in ai_msgs[-1]

    def test_build_langchain_messages_toolmessage(self, handler):
        """_build_langchain_messages should convert ToolMessage correctly."""
        history = [ToolMessage(content="result data", tool_call_id="tc_1")]
        result = handler._build_langchain_messages(
            langchain_history=history,
            system_prompt="Be helpful.",
            user_input="Done?",
        )
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "tool"
        assert result[1]["tool_call_id"] == "tc_1"
        assert result[1]["content"] == "result data"
        assert result[2]["role"] == "user"

    @patch("animetta.services.llm.tool_handler.logger")
    async def test_chat_with_tools_success(self, mock_logger, handler, mock_openai_llm):
        """chat_with_tools should return content for a non-tool response."""
        mock_choice = MagicMock()
        mock_choice.message.content = "The weather is sunny."
        mock_choice.message.tool_calls = None

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await handler.chat_with_tools(
            user_input="Weather in Paris?",
            tools=[fake_weather],
            langchain_history=[],
        )

        assert result["content"] == "The weather is sunny."
        assert result["tool_calls"] is None
        mock_openai_llm._record_usage.assert_called_once()

    @patch("animetta.services.llm.tool_handler.logger")
    async def test_chat_with_tools_with_tool_calls(self, mock_logger, handler, mock_openai_llm):
        """chat_with_tools should return tool_calls when the model requests them."""
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_abc"
        mock_tool_call.function.name = "fake_weather"
        mock_tool_call.function.arguments = '{"city": "Paris"}'

        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.message.tool_calls = [mock_tool_call]

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_openai_llm.client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )

        result = await handler.chat_with_tools(
            user_input="Weather in Paris?",
            tools=[fake_weather],
            langchain_history=[],
        )

        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_abc"
        assert result["tool_calls"][0]["name"] == "fake_weather"
        assert result["tool_calls"][0]["args"] == {"city": "Paris"}

    @patch("animetta.services.llm.tool_handler.logger")
    async def test_chat_with_tools_error(self, mock_logger, handler, mock_openai_llm):
        """chat_with_tools should raise on API error after recording it."""
        mock_openai_llm.client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )

        with pytest.raises(Exception, match="API error"):
            await handler.chat_with_tools(
                user_input="hi",
                tools=[],
                langchain_history=[],
            )

        mock_openai_llm._record_error.assert_called_once()
