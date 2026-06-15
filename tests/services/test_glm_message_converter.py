from __future__ import annotations

"""Tests for GLM message format converter.

Covers conversion between LangChain message types and the GLM API
format used by Zhipu AI's chat completion endpoint.
"""

import json
from unittest.mock import MagicMock

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from animetta.services.llm.glm_message_converter import (
    GLMMessageConverter,
    GLMToolConverter,
)

# ═══════════════════════════════════════════════════════════════════════
# GLMMessageConverter
# ═══════════════════════════════════════════════════════════════════════


class TestGLMMessageConverterConvertToGLM:
    """GLMMessageConverter.convert_to_glm() — LangChain → GLM format."""

    def test_converts_system_message(self):
        msg = SystemMessage(content="You are a helpful assistant.")
        result = GLMMessageConverter.convert_to_glm(msg)

        assert result == {"role": "system", "content": "You are a helpful assistant."}

    def test_converts_human_message(self):
        msg = HumanMessage(content="Hello!")
        result = GLMMessageConverter.convert_to_glm(msg)

        assert result == {"role": "user", "content": "Hello!"}

    def test_converts_ai_message(self):
        msg = AIMessage(content="Hi there!")
        result = GLMMessageConverter.convert_to_glm(msg)

        assert result == {"role": "assistant", "content": "Hi there!"}

    def test_converts_ai_message_with_tool_calls(self):
        msg = AIMessage(
            content="Let me look that up.",
            tool_calls=[
                {
                    "id": "call_123",
                    "name": "web_search",
                    "args": {"query": "weather"},
                }
            ],
        )
        result = GLMMessageConverter.convert_to_glm(msg)

        assert result["role"] == "assistant"
        assert result["content"] == "Let me look that up."
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_123"
        assert result["tool_calls"][0]["function"]["name"] == "web_search"
        assert json.loads(result["tool_calls"][0]["function"]["arguments"]) == {"query": "weather"}

    def test_converts_ai_message_empty_content_with_tool_calls(self):
        """AIMessage with no text but with tool calls."""
        msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "calculator", "args": {"expr": "1+1"}},
            ],
        )
        result = GLMMessageConverter.convert_to_glm(msg)

        assert result["content"] == ""
        assert len(result["tool_calls"]) == 1

    def test_converts_tool_message(self):
        msg = ToolMessage(
            content='{"result": 42}',
            tool_call_id="call_123",
        )
        result = GLMMessageConverter.convert_to_glm(msg)

        assert result == {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": '{"result": 42}',
        }

    def test_converts_fallback_for_unknown_message_type(self):
        """Messages that match no known type fall back to user role."""
        msg = MagicMock()
        msg.content = "custom payload"

        result = GLMMessageConverter.convert_to_glm(msg)
        assert result == {"role": "user", "content": "custom payload"}

    def test_fallback_without_content_attribute(self):
        """Fallback handles objects without a content attribute."""
        msg = object()

        result = GLMMessageConverter.convert_to_glm(msg)
        # str(object()) gives something like "<object object at 0x...>"
        assert result["role"] == "user"
        assert isinstance(result["content"], str)


# ═══════════════════════════════════════════════════════════════════════
# GLMToolConverter
# ═══════════════════════════════════════════════════════════════════════


class _FakeTool:
    """Minimal stand-in for a LangChain BaseTool."""

    def __init__(self, name="test_tool", description="A test tool", args_schema=None):
        self.name = name
        self.description = description
        self.args_schema = args_schema


class _FakeArgsSchema:
    """Stand-in for a Pydantic args_schema with a .schema() method."""

    @staticmethod
    def schema():
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }


class TestGLMToolConverterConvertTools:
    """GLMToolConverter.convert_tools() — LangChain tools → GLM format."""

    def test_converts_single_tool(self):
        tool = _FakeTool(
            name="web_search",
            description="Search the web",
            args_schema=_FakeArgsSchema(),
        )
        result = GLMToolConverter.convert_tools([tool])

        assert len(result) == 1
        glm_tool = result[0]
        assert glm_tool["type"] == "function"
        assert glm_tool["function"]["name"] == "web_search"
        assert glm_tool["function"]["description"] == "Search the web"
        assert "parameters" in glm_tool["function"]

    def test_converts_multiple_tools(self):
        tools = [
            _FakeTool(name="search", description="Search tool", args_schema=_FakeArgsSchema()),
            _FakeTool(name="calculator", description="Calculate", args_schema=None),
        ]
        result = GLMToolConverter.convert_tools(tools)

        assert len(result) == 2
        assert result[0]["function"]["name"] == "search"
        assert result[1]["function"]["name"] == "calculator"

    def test_tool_without_args_schema_uses_empty_parameters(self):
        tool = _FakeTool(name="no_args_tool", description="Tool with no args", args_schema=None)
        result = GLMToolConverter.convert_tools([tool])

        params = result[0]["function"]["parameters"]
        assert params == {"type": "object", "properties": {}, "required": []}

    def test_parameter_schema_includes_properties_and_required(self):
        tool = _FakeTool(name="search", description="Search", args_schema=_FakeArgsSchema())
        result = GLMToolConverter.convert_tools([tool])

        params = result[0]["function"]["parameters"]
        assert "properties" in params
        assert "required" in params
        assert params["required"] == ["query"]

    def test_parameter_schema_preserves_types(self):
        tool = _FakeTool(name="search", description="Search", args_schema=_FakeArgsSchema())
        result = GLMToolConverter.convert_tools([tool])

        query_prop = result[0]["function"]["parameters"]["properties"]["query"]
        assert query_prop["type"] == "string"


# ═══════════════════════════════════════════════════════════════════════
# GLMToolConverter.parse_tool_response
# ═══════════════════════════════════════════════════════════════════════


class _FakeToolCall:
    """Stand-in for a GLM API response tool_call object."""

    def __init__(self, id="call_1", name="web_search", args=None):
        self.id = id
        self.function = MagicMock()
        self.function.name = name
        self.function.arguments = json.dumps(args or {})


class TestGLMToolConverterParseToolResponse:
    """GLMToolConverter.parse_tool_response() — GLM response → structured dict."""

    def test_parses_response_with_tool_calls(self):
        message = MagicMock()
        message.content = "I will search for you."
        tc = _FakeToolCall(id="call_1", name="web_search", args={"query": "weather"})
        message.tool_calls = [tc]

        result = GLMToolConverter.parse_tool_response(message)

        assert result["content"] == "I will search for you."
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_1"
        assert result["tool_calls"][0]["name"] == "web_search"
        assert result["tool_calls"][0]["args"] == {"query": "weather"}

    def test_parses_response_without_tool_calls(self):
        message = MagicMock()
        message.content = "Hello!"
        message.tool_calls = None

        result = GLMToolConverter.parse_tool_response(message)

        assert result["content"] == "Hello!"
        assert result["tool_calls"] is None

    def test_parses_response_with_empty_content(self):
        """Empty content gets a default fallback message when tool calls exist."""
        message = MagicMock()
        message.content = ""
        tc = _FakeToolCall(id="call_2", name="calculator", args={"expr": "1+1"})
        message.tool_calls = [tc]

        result = GLMToolConverter.parse_tool_response(message)

        assert result["content"] == "正在调用工具..."
        assert len(result["tool_calls"]) == 1

    def test_handles_string_arguments_parsing(self):
        """String arguments are JSON-parsed into dicts."""
        message = MagicMock()
        message.content = "Working..."
        tc = _FakeToolCall(id="call_3", name="search", args={"q": "hello"})
        # Override to return a raw JSON string
        tc.function.arguments = '{"q": "hello"}'
        message.tool_calls = [tc]

        result = GLMToolConverter.parse_tool_response(message)

        assert result["tool_calls"][0]["args"] == {"q": "hello"}


# ═══════════════════════════════════════════════════════════════════════
# Integration: convert messages -> send to GLM -> parse response
# ═══════════════════════════════════════════════════════════════════════


class TestGLMConverterIntegration:
    """End-to-end message conversion flow."""

    def test_round_trip_messages_and_tools(self):
        """Convert LangChain messages + tools to GLM format."""
        messages = [
            SystemMessage(content="Be helpful."),
            HumanMessage(content="What's 2+2?"),
            AIMessage(content="Let me calculate."),
        ]
        tools = [
            _FakeTool(
                name="calculator",
                description="Do math",
                args_schema=_FakeArgsSchema(),
            ),
        ]

        glm_messages = [GLMMessageConverter.convert_to_glm(m) for m in messages]
        glm_tools = GLMToolConverter.convert_tools(tools)

        assert len(glm_messages) == 3
        assert glm_messages[0] == {"role": "system", "content": "Be helpful."}
        assert glm_messages[1] == {"role": "user", "content": "What's 2+2?"}
        assert glm_messages[2] == {"role": "assistant", "content": "Let me calculate."}
        assert len(glm_tools) == 1
        assert glm_tools[0]["function"]["name"] == "calculator"
