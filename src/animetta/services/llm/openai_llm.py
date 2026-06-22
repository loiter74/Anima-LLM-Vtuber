from __future__ import annotations

"""
OpenAI LLM implementation
Uses the openai SDK to call OpenAI GPT models
"""

import time as time_module
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

from animetta.core.config.core.registry import ProviderRegistry

from .interface import LLMInterface
from .stream_handler import OpenAIStreamHandler
from .tool_handler import OpenAIToolHandler


@ProviderRegistry.register_service("llm", "openai")
@ProviderRegistry.register_service("llm", "deepseek")
class OpenAILLM(LLMInterface):
    """
    OpenAI GPT model Agent implementation

    Uses the official openai SDK to call GPT-4, GPT-3.5, and other models
    Supports streaming output and custom base_url (compatible with other OpenAI API-compatible services)
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        system_prompt: str = "",
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ):
        """
        Initialize OpenAI LLM

        Args:
            api_key: OpenAI API Key
            model: Model name (gpt-4, gpt-4o, gpt-3.5-turbo, etc.)
            system_prompt: System prompt
            base_url: Custom API endpoint (optional)
            temperature: Temperature parameter
            max_tokens: Maximum number of tokens to generate
        """
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Conversation history
        self.history: list[dict[str, str]] = []

        # Initialize async client for connection stability
        import httpx
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
        client_kwargs = {"api_key": api_key, "http_client": http_client}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = AsyncOpenAI(**client_kwargs)

        # Initialize handler instances
        self.stream_handler = OpenAIStreamHandler(self)
        self.tool_handler = OpenAIToolHandler(self)

        logger.info(f"OpenAILLM initialized: model={model}, base_url={base_url or 'default'}")

    @classmethod
    def from_config(cls, config: LLMBaseConfig, system_prompt: str = "", **kwargs) -> OpenAILLM:
        """
        Create an instance from a configuration object

        Supports:
        - OpenAILLMConfig (type: openai)
        - DeepSeekLLMConfig (type: deepseek) — OpenAI API compatible

        Args:
            config: LLM configuration object (OpenAILLMConfig or DeepSeekLLMConfig)
            system_prompt: System prompt
            **kwargs: Additional parameters (ignored)

        Returns:
            OpenAILLM instance
        """
        # Extract common fields from config (compatible with OpenAI / DeepSeek and other OpenAI API-compatible services)
        api_key = getattr(config, 'api_key', '')
        model = getattr(config, 'model', 'gpt-4o-mini')
        base_url = getattr(config, 'base_url', None)
        temperature = getattr(config, 'temperature', 0.7)
        max_tokens = getattr(config, 'max_tokens', 1000)

        return cls(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _build_messages(self, user_input: str, system_prompt: str | None = None) -> list[dict[str, str]]:
        """
        Build messages list

        Args:
            user_input: User input
            system_prompt: Dynamic system prompt (overrides self.system_prompt, used for RAG memory enhancement)

        Returns:
            List[Dict[str, str]]: Complete messages list
        """
        messages = []

        # Use the passed-in system_prompt (RAG enhanced), otherwise use the instance default
        effective_prompt = system_prompt if system_prompt is not None else self.system_prompt
        if effective_prompt:
            messages.append({
                "role": "system",
                "content": effective_prompt
            })

        # Add conversation history
        messages.extend(self.history)

        # Add current user input
        messages.append({
            "role": "user",
            "content": user_input
        })

        return messages

    async def chat(self, user_input: str, **kwargs) -> str:
        """
        Chat with the OpenAI model

        Args:
            user_input: User input
            **kwargs: Supports system_prompt — dynamically overrides the system prompt

        Returns:
            str: Model response
        """
        system_prompt = kwargs.get("system_prompt")
        messages = self._build_messages(user_input, system_prompt=system_prompt)

        t_start = time_module.perf_counter()
        try:
            response = await self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens)
            )

            assistant_message = response.choices[0].message.content

            # OTel metrics: record token usage + cost + duration
            duration_s = time_module.perf_counter() - t_start
            self._record_usage(response, duration_s)

            # Update history
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": assistant_message})

            logger.debug(f"OpenAI response: {assistant_message[:100]}...")
            return assistant_message

        except Exception as e:
            duration_s = time_module.perf_counter() - t_start
            self._record_error(duration_s)
            logger.error(f"OpenAI chat error: {e}")
            raise

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        """
        Chat using messages-based protocol with native OpenAI API.

        Overrides the default serialization to call OpenAI's
        client.chat.completions.create directly, preserving
        response_format, model, and temperature kwargs.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            **kwargs: Additional parameters (response_format, model, temperature, etc.)

        Returns:
            str: Model response
        """
        create_kwargs = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }
        if "response_format" in kwargs:
            create_kwargs["response_format"] = kwargs["response_format"]

        t_start = time_module.perf_counter()
        try:
            response = await self.client.chat.completions.create(**create_kwargs)
            assistant_message = response.choices[0].message.content

            # OTel metrics
            duration_s = time_module.perf_counter() - t_start
            self._record_usage(response, duration_s)

            logger.debug(f"OpenAI chat_messages response: {assistant_message[:100]}...")
            return assistant_message

        except Exception as e:
            duration_s = time_module.perf_counter() - t_start
            self._record_error(duration_s)
            logger.error(f"OpenAI chat_messages error: {e}")
            raise

    async def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        """
        Streaming chat

        Args:
            user_input: User input
            **kwargs: Supports system_prompt — dynamically overrides the system prompt (RAG memory enhancement)

        Yields:
            str: Text chunk of the model response
        """
        async for chunk in self.stream_handler.stream(user_input, **kwargs):
            yield chunk

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt"""
        self.system_prompt = prompt
        logger.debug(f"System prompt updated: {prompt[:50]}...")

    def get_history(self) -> list[dict[str, Any]]:
        """Get conversation history"""
        return self.history.copy()

    def clear_history(self) -> None:
        """Clear conversation history"""
        self.history.clear()
        logger.debug("Conversation history cleared")

    async def close(self) -> None:
        """Clean up resources"""
        await self.client.close()
        logger.info("OpenAILLM resources released")

    def _get_provider_name(self) -> str:
        """Infer provider name from base_url."""
        if self.base_url and "deepseek" in str(self.base_url).lower():
            return "deepseek"
        return "openai"

    def _record_usage(self, response: Any, duration_s: float) -> None:
        """Record OTel metrics for token usage, cost, and duration."""
        try:
            input_tokens = 0
            output_tokens = 0

            if hasattr(response, "usage") and response.usage:
                input_tokens = getattr(response.usage, "prompt_tokens", 0)
                output_tokens = getattr(response.usage, "completion_tokens", 0)

            provider = self._get_provider_name()
            model = self.model


            # Duration
            dur = get_llm_request_duration()
            if dur is not None:
                dur.observe(duration_s, {"provider": provider, "model": model})

            # Tokens
            tok = get_llm_tokens()
            if tok is not None:
                if input_tokens > 0:
                    tok.add(input_tokens, {"provider": provider, "model": model, "type": "input"})
                if output_tokens > 0:
                    tok.add(output_tokens, {"provider": provider, "model": model, "type": "output"})

            # Cost
            cost = calculate_cost(provider, model, input_tokens, output_tokens)
            if cost > 0:
                cst = get_llm_cost()
                if cst is not None:
                    cst.add(cost, {"provider": provider, "model": model})

        except Exception:
            pass

    def _record_error(self, duration_s: float) -> None:
        """Record LLM error metrics."""
        try:
            provider = self._get_provider_name()
            err = get_llm_errors()
            if err is not None:
                err.add(1, {"provider": provider, "model": self.model})
            if _PROM_LLM_ERRORS is not None:
                _PROM_LLM_ERRORS.labels(provider=provider, model=self.model).inc()
            dur = get_llm_request_duration()
            if dur is not None and duration_s > 0:
                dur.observe(duration_s, {"provider": provider, "model": self.model})
        except Exception:
            pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        """
        Handle user interruption

        Args:
            heard_response: Partial response heard by the user
        """
        if heard_response and self.history and self.history[-1].get("role") == "user":
            # Save partial response to history
            # Get the last user input
            self.history[-1].get("content", "")
            # Add partial AI response
            self.history.append({
                "role": "assistant",
                "content": heard_response
            })
            # Add interruption marker
            self.history.append({
                "role": "system",
                "content": "[user interrupted the conversation]"
            })

        logger.info(f"Conversation interrupted, partial response saved: {heard_response[:50] if heard_response else '(empty)'}...")

    def set_memory_from_history(
        self,
        conf_uid: str,
        history_uid: str
    ) -> None:
        """
        Restore conversation memory from history records

        Args:
            conf_uid: Config UID
            history_uid: History UID
        """
        # TODO: Implement loading history from persistent storage
        # For now, just log it
        logger.info(f"Attempting to restore memory from history: conf_uid={conf_uid}, history_uid={history_uid}")

    # ================================================================
    # LangGraph tool calling interface (delegated to OpenAIToolHandler)
    # ================================================================

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
        return await self.tool_handler.chat_with_tools(
            user_input=user_input,
            tools=tools,
            langchain_history=langchain_history,
            system_prompt=system_prompt,
        )
