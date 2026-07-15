from __future__ import annotations

"""
OpenAI LLM tool handler — handles tool calling logic.

Extracted from openai_llm.py to separate tool calling concerns from
core LLM implementation.
"""

import json
import time as time_module
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

if TYPE_CHECKING:
    from .openai_llm import OpenAILLM


def _get_args_schema_parameters(args_schema: Any) -> dict[str, Any]:
    if hasattr(args_schema, "model_json_schema"):
        return args_schema.model_json_schema()
    return args_schema.schema()


class OpenAIToolHandler:
    """
    Handles tool calling for OpenAILLM.

    Encapsulates: tool format conversion, LangChain message building,
    and the chat_with_tools invocation with result processing.
    """

    def __init__(self, llm_instance: OpenAILLM):
        """
        Args:
            llm_instance: The OpenAILLM instance that owns this handler.
        """
        self.llm = llm_instance

    def _convert_tools_to_openai(self, tools: list[Any]) -> list[dict[str, Any]]:
        """
        Convert a list of LangChain tools to OpenAI API format

        Args:
            tools: List of LangChain BaseTool objects

        Returns:
            Tool list in OpenAI API format
        """
        openai_tools = []
        for tool in tools:
            parameters = {"type": "object", "properties": {}}
            if hasattr(tool, "args_schema") and tool.args_schema:
                try:
                    parameters = _get_args_schema_parameters(tool.args_schema)
                except Exception:
                    parameters = {"type": "object", "properties": {}}

            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": parameters,
                    },
                }
            )
        return openai_tools

    def _build_langchain_messages(
        self,
        langchain_history: list[Any],
        system_prompt: str | None,
        user_input: str,
    ) -> list[dict[str, Any]]:
        """
        Build an OpenAI API message list from LangChain messages

        Args:
            langchain_history: LangChain message history
            system_prompt: System prompt
            user_input: User input

        Returns:
            Message list in OpenAI API format
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in langchain_history:
            if isinstance(msg, SystemMessage):
                messages.append({"role": "system", "content": msg.content})
            elif isinstance(msg, HumanMessage):
                messages.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                ai_msg = {"role": "assistant", "content": msg.content or ""}
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    ai_msg["tool_calls"] = [
                        {
                            "id": tc.get("id", "")
                            if isinstance(tc, dict)
                            else getattr(tc, "id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", "")
                                if isinstance(tc, dict)
                                else getattr(tc, "name", ""),
                                "arguments": json.dumps(
                                    tc.get("args", {})
                                    if isinstance(tc, dict)
                                    else getattr(tc, "args", {}),
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for tc in (msg.tool_calls if hasattr(msg, "tool_calls") else [])
                    ]
                messages.append(ai_msg)
            elif isinstance(msg, ToolMessage):
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )

        messages.append({"role": "user", "content": user_input})
        return messages

    async def chat_with_tools(
        self,
        user_input: str,
        tools: list[Any],
        langchain_history: list[Any],
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Conversation with tool calls (LangGraph specific)

        Args:
            user_input: User input
            tools: List of LangChain tools
            langchain_history: LangChain message history
            system_prompt: System prompt

        Returns:
            Dict: Response containing content and tool_calls
        """
        openai_tools = self._convert_tools_to_openai(tools)
        messages = self._build_langchain_messages(langchain_history, system_prompt, user_input)

        logger.debug(
            f"[OpenAI] chat_with_tools: tools={len(openai_tools)}, input={user_input[:50]}"
        )

        t_start = time_module.perf_counter()
        try:
            response = await self.llm.client.chat.completions.create(
                model=self.llm.model,
                messages=messages,
                tools=openai_tools if openai_tools else None,
                tool_choice="auto" if openai_tools else None,
                temperature=self.llm.temperature,
                top_p=self.llm.top_p,
                max_tokens=self.llm.max_tokens,
                stream=False,
                **({"extra_body": self.llm.extra_body} if self.llm.extra_body else {}),
            )

            # OTel metrics: record token usage + cost + duration
            duration_s = time_module.perf_counter() - t_start
            self.llm._record_usage(response, duration_s)

            message = response.choices[0].message
            content = message.content or ""

            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    args = tc.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}

                    tool_calls.append(
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "args": args,
                        }
                    )

                logger.info(f"[OpenAI] Tool calls: {[tc['name'] for tc in tool_calls]}")
                return {
                    "content": content or "Calling tool......",
                    "tool_calls": tool_calls,
                }

            logger.debug(f"[OpenAI] Response: {content[:100]}...")

            # Update conversation history
            self.llm.history.append({"role": "user", "content": user_input})
            self.llm.history.append({"role": "assistant", "content": content})

            return {
                "content": content,
                "tool_calls": None,
            }

        except Exception as e:
            duration_s = time_module.perf_counter() - t_start if "t_start" in dir() else 0
            self.llm._record_error(duration_s)
            logger.exception(f"[OpenAI] Tool call failed: {type(e).__name__}: {e}")
            raise
