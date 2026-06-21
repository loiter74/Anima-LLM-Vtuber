from __future__ import annotations

"""
GLM message format converter
Handles conversion between LangChain messages and GLM API format
"""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def _get_args_schema_parameters(args_schema: Any) -> dict[str, Any]:
    if hasattr(args_schema, "model_json_schema"):
        return args_schema.model_json_schema()
    return args_schema.schema()


class GLMMessageConverter:
    """Converts LangChain messages to GLM API format"""

    @staticmethod
    def convert_to_glm(msg: Any) -> dict[str, Any]:
        """
        Convert a LangChain message to GLM API format

        Args:
            msg: LangChain message object

        Returns:
            Dict: Message in GLM API format
        """
        if isinstance(msg, SystemMessage):
            return GLMMessageConverter._convert_system(msg)
        elif isinstance(msg, HumanMessage):
            return GLMMessageConverter._convert_human(msg)
        elif isinstance(msg, AIMessage):
            return GLMMessageConverter._convert_ai(msg)
        elif isinstance(msg, ToolMessage):
            return GLMMessageConverter._convert_tool(msg)
        else:
            return GLMMessageConverter._convert_fallback(msg)

    @staticmethod
    def _convert_system(msg: SystemMessage) -> dict[str, Any]:
        return {"role": "system", "content": msg.content}

    @staticmethod
    def _convert_human(msg: HumanMessage) -> dict[str, Any]:
        return {"role": "user", "content": msg.content}

    @staticmethod
    def _convert_ai(msg: AIMessage) -> dict[str, Any]:
        glm_msg = {"role": "assistant", "content": msg.content or ""}

        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            glm_msg["tool_calls"] = [
                GLMMessageConverter._convert_tool_call(tc)
                for tc in msg.tool_calls
            ]

        return glm_msg

    @staticmethod
    def _convert_tool_call(tc: Any) -> dict[str, Any]:
        """Convert a single tool call"""
        if isinstance(tc, dict):
            tc_id = tc.get("id", "")
            tc_name = tc.get("name", "")
            tc_args = tc.get("args", {})
        else:
            tc_id = getattr(tc, 'id', '')
            tc_name = getattr(tc, 'name', '')
            tc_args = getattr(tc, 'args', {})

        arguments_str = tc_args if isinstance(tc_args, str) else json.dumps(tc_args, ensure_ascii=False)

        return {
            "id": tc_id,
            "type": "function",
            "function": {
                "name": tc_name,
                "arguments": arguments_str,
            }
        }

    @staticmethod
    def _convert_tool(msg: ToolMessage) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id,
            "content": msg.content,
        }

    @staticmethod
    def _convert_fallback(msg: Any) -> dict[str, Any]:
        content = str(msg.content) if hasattr(msg, 'content') else str(msg)
        return {"role": "user", "content": content}


class GLMToolConverter:
    """Converts LangChain tools to GLM API format"""

    @staticmethod
    def convert_tools(tool_list: list[Any]) -> list[dict[str, Any]]:
        """
        Convert a list of LangChain tools to GLM format

        Args:
            tool_list: List of LangChain BaseTool objects

        Returns:
            List[Dict]: Tool list in GLM API format
        """
        glm_tools = []

        for tool in tool_list:
            parameters = GLMToolConverter._get_tool_parameters(tool)

            glm_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": parameters,
                }
            })

        return glm_tools

    @staticmethod
    def _get_tool_parameters(tool: Any) -> dict[str, Any]:
        """Get tool parameter schema"""
        if hasattr(tool, "args_schema") and tool.args_schema:
            return _get_args_schema_parameters(tool.args_schema)
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    @staticmethod
    def parse_tool_response(message: Any) -> dict[str, Any]:
        """
        Parse tool calls from a GLM API response

        Args:
            message: GLM API response message object

        Returns:
            Dict: Dictionary containing content and tool_calls
        """
        content = message.content or ""
        tool_calls = []

        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json.loads(args)

                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": args,
                })

        return {
            "content": content or "正在调用工具...",
            "tool_calls": tool_calls if tool_calls else None,
        }
