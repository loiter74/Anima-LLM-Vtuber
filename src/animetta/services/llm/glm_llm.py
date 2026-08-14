from __future__ import annotations

"""
GLM (ZhipuAI) LLM implementation
Uses the zhipuai SDK to call Zhipu AI's GLM models

"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from loguru import logger
from zhipuai import ZhipuAI

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.llm.glm import GLMLLMConfig

from .glm_message_converter import GLMMessageConverter, GLMToolConverter
from .interface import LLMInterface


@ProviderRegistry.register_service("llm", "glm")
class GLMLLM(LLMInterface):
    """GLM (Zhipu AI) LLM implementation"""

    def __init__(self, config: GLMLLMConfig):
        self.config = config
        self.client = None
        self._conversation_history: list[dict[str, Any]] = []
        self._call_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    @classmethod
    def from_config(cls, config: GLMLLMConfig, **kwargs):
        return cls(config=config)

    async def _ensure_client(self):
        if self.client is None:
            self.client = ZhipuAI(api_key=self.config.api_key, disable_token_cache=False)
            logger.info("[GLM] ZhipuAI client initialized")

    async def preload(self) -> None:
        """Preload the ZhipuAI API client (lightweight, idempotent)"""
        if self.client is not None:
            return
        await self._ensure_client()
        logger.info(f"[GLM] API client preloaded (model={self.config.model})")

    async def chat_stream(
        self,
        user_input: str,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        del kwargs
        await self._ensure_client()

        messages = self._build_messages(user_input, system_prompt, include_history=True)
        glm_tools = self._convert_tools_if_needed(tools)

        logger.debug(
            f"[GLM] Sending message, history count: {len(self._conversation_history)}, tools count: {len(glm_tools) if glm_tools else 0}"
        )

        try:

            def _create_stream():
                return self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=glm_tools,
                    stream=True,
                    temperature=self.config.temperature,
                )

            response = await asyncio.to_thread(_create_stream)
            full_response = ""

            for chunk in response:
                content = self._extract_chunk_content(chunk)
                if content:
                    full_response += content
                    yield content

            self._update_history(user_input, full_response)

        except Exception as e:
            logger.error(f"[GLM] Chat failed: {e}")
            raise

    async def chat(
        self,
        user_input: str,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> str:
        del kwargs
        await self._ensure_client()

        messages = self._build_messages(user_input, system_prompt, include_history=True)
        glm_tools = self._convert_tools_if_needed(tools)

        try:

            def _create_completion():
                return self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=glm_tools,
                    stream=False,
                    temperature=self.config.temperature,
                )

            response = await asyncio.to_thread(_create_completion)
            full_response = response.choices[0].message.content

            # Track token usage
            self._track_usage(response)

            self._update_history(user_input, full_response)
            return full_response

        except Exception as e:
            logger.error(f"[GLM] Chat failed: {e}")
            raise

    async def chat_messages(self, messages: list[dict], **kwargs: Any) -> str:
        """Call GLM with an explicit, history-neutral message list."""
        await self._ensure_client()

        def _create_completion():
            return self.client.chat.completions.create(
                model=kwargs.get("model", self.config.model),
                messages=messages,
                stream=False,
                temperature=kwargs.get("temperature", self.config.temperature),
                **(
                    {"response_format": kwargs["response_format"]}
                    if "response_format" in kwargs
                    else {}
                ),
            )

        response = await asyncio.to_thread(_create_completion)
        self._track_usage(response)
        return response.choices[0].message.content or ""

    async def chat_messages_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream GLM output using only the supplied messages."""
        await self._ensure_client()

        def _create_stream():
            return self.client.chat.completions.create(
                model=kwargs.get("model", self.config.model),
                messages=messages,
                stream=True,
                temperature=kwargs.get("temperature", self.config.temperature),
            )

        response = await asyncio.to_thread(_create_stream)
        for chunk in response:
            content = self._extract_chunk_content(chunk)
            if content:
                yield content

    async def chat_with_tools(
        self,
        user_input: str,
        tools: list[Any],
        langchain_history: list[Any],
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Conversation with tool calls (LangGraph specific)"""
        await self._ensure_client()

        logger.debug(
            f"[GLM] chat_with_tools called: tools={len(tools)}, user_input={user_input[:50]}"
        )

        glm_tools = GLMToolConverter.convert_tools(tools)
        messages = self._build_langchain_messages(langchain_history, system_prompt, user_input)

        logger.debug(
            f"[GLM] Sending message (tool mode), tools: {len(glm_tools)}, history: {len(messages)}"
        )

        try:

            def _create_completion():
                return self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=glm_tools,
                    tool_choice="auto",
                    stream=False,
                    temperature=self.config.temperature,
                )

            response = await asyncio.to_thread(_create_completion)

            # Token 追踪
            self._track_usage(response)

            return GLMToolConverter.parse_tool_response(response.choices[0].message)

        except Exception as e:
            logger.error(f"[GLM] Tool call failed: {e}")
            raise

    def _track_usage(self, response: Any) -> None:
        """Track token consumption and record OTel metrics."""
        try:
            usage = getattr(response, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0
                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                logger.debug(
                    f"[GLM] Token usage: input={input_tokens}, output={output_tokens}, "
                    f"cumulative input={self._total_input_tokens}, output={self._total_output_tokens}"
                )

        except Exception as e:
            logger.debug(f"[GLM] Token tracking failed: {e}")

    def get_token_usage(self) -> dict[str, int]:
        """Get cumulative token usage"""
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "total_tokens": self._total_input_tokens + self._total_output_tokens,
            "call_count": self._call_count,
        }

    def _build_messages(
        self, prompt: str, system_prompt: str | None, include_history: bool = True
    ) -> list[dict[str, Any]]:
        """Build messages list"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if include_history:
            for msg in self._conversation_history:
                messages.append(msg.copy() if isinstance(msg, dict) else msg)

        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_langchain_messages(
        self, langchain_history: list[Any], system_prompt: str | None, user_input: str
    ) -> list[dict[str, Any]]:
        """Build GLM messages from LangChain history"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in langchain_history:
            glm_msg = GLMMessageConverter.convert_to_glm(msg)
            messages.append(glm_msg)
            logger.debug(
                f"[GLM] Converted history message: {type(msg).__name__} -> {glm_msg.get('role')}"
            )

        last_history_message = langchain_history[-1] if langchain_history else None
        if not isinstance(last_history_message, ToolMessage) and not (
            isinstance(last_history_message, HumanMessage)
            and last_history_message.content == user_input
        ):
            messages.append({"role": "user", "content": user_input})
        return messages

    def _convert_tools_if_needed(self, tools: list[Any] | None) -> list[dict] | None:
        """Convert tool format if there are tool calls in history"""
        if not tools:
            return None

        has_tool_calls = any(
            msg.get("role") == "assistant" and "tool_calls" in msg
            for msg in self._conversation_history
        )

        if has_tool_calls:
            return GLMToolConverter.convert_tools(tools)
        return None

    def _extract_chunk_content(self, chunk: Any) -> str:
        """Extract content from a streaming response chunk"""
        if hasattr(chunk, "choices") and chunk.choices:
            delta = chunk.choices[0].delta
            if hasattr(delta, "content") and delta.content:
                return delta.content
        elif hasattr(chunk, "content") and chunk.content:
            return chunk.content
        return ""

    def _update_history(self, user_input: str, response: str):
        """Update conversation history"""
        self._conversation_history.append({"role": "user", "content": user_input})
        self._conversation_history.append({"role": "assistant", "content": response})

        self._call_count += 1

        self._conversation_history = self._trim_history(
            self._conversation_history, getattr(self.config, "max_history_messages", 20)
        )

    def clear_history(self) -> None:
        self._conversation_history = []
        logger.debug("[GLM] Conversation history cleared")

    def set_system_prompt(self, prompt: str) -> None:
        self._conversation_history = [
            msg for msg in self._conversation_history if msg.get("role") != "system"
        ]
        if prompt:
            self._conversation_history.insert(0, {"role": "system", "content": prompt})
        logger.debug(f"[GLM] System prompt updated: {prompt[:50]}...")

    def get_history(self) -> list[dict[str, Any]]:
        return self._conversation_history.copy()

    def handle_interrupt(self, heard_response: str = "") -> None:
        if (
            heard_response
            and self._conversation_history
            and self._conversation_history[-1].get("role") == "user"
        ):
            self._conversation_history.append({"role": "assistant", "content": heard_response})
            self._conversation_history.append({"role": "system", "content": "[用户打断了对话]"})
            self._conversation_history = self._trim_history(
                self._conversation_history, getattr(self.config, "max_history_messages", 20)
            )
        logger.info(
            f"[GLM] Conversation interrupted, partial response saved: {heard_response[:50] if heard_response else '(empty)'}..."
        )

    @property
    def max_tokens(self) -> int | None:
        return self.config.max_tokens

    def set_max_tokens(self, max_tokens: int) -> None:
        self.config.max_tokens = max_tokens

    def supports_tool_calls(self) -> bool:
        return self.config.model.startswith("glm-4")

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        logger.info(
            f"[GLM] Attempting to restore memory from history: conf_uid={conf_uid}, history_uid={history_uid}"
        )

    async def close(self) -> None:
        self.client = None
        logger.info("[GLM] Connection closed")
