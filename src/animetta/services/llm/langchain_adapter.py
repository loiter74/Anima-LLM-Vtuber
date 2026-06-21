from __future__ import annotations

"""
LangChain ChatModel adapter

Wraps existing LLM services as LangChain's BaseChatModel,
enabling advanced features such as bind_tools().

Note: Actual tool calls are handled directly by llm_node.py; this adapter is for basic conversation only.
"""

import inspect
from collections.abc import Sequence
from typing import Any, TypeVar

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from loguru import logger

# Pydantic v1/v2 compatibility handling
try:
    from pydantic import Field
except ImportError:
    from pydantic.v1 import Field

# Import existing LLM interface
from ..llm.interface import LLMInterface

GenericChatModel = TypeVar("GenericChatModel", bound="LLMChatModelAdapter")


class LLMChatModelAdapter(BaseChatModel):
    """
    LangChain ChatModel adapter

    Wraps an existing LLMInterface implementation to make it compatible with LangChain's BaseChatModel protocol.
    """

    llm_service: LLMInterface = Field(description="Existing LLM service instance")
    bound_tools: Sequence[BaseTool] = Field(default_factory=list, description="Bound tool list")
    model_name: str = Field(default="unknown", description="Model name (used for LangSmith/LangFuse tracing)")

    # LangChain required fields
    @property
    def _llm_type(self) -> str:
        return f"anima_{self.model_name}"

    @property
    def lc_secrets(self) -> dict[str, str]:
        """Hide sensitive information"""
        return {}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Synchronous generation (delegates to async version)

        Note: The existing LLM service is async; this bridges sync→async.
        Uses asyncio.run() when no running loop exists (safe path),
        or run_until_complete with the current loop when called from async context.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # Called from async context — use run_until_complete to avoid
            # "asyncio.run() cannot be called from a running event loop"
            return loop.run_until_complete(
                asyncio.ensure_future(self._agenerate(messages, stop, run_manager, **kwargs))
            )
        except RuntimeError:
            # No running loop — safe to use asyncio.run()
            return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Asynchronously generate a response

        Args:
            messages: List of messages
            stop: Stop words
            run_manager: Callback manager
            **kwargs: Additional parameters

        Returns:
            ChatResult: Generation result
        """
        # Extract user input (last HumanMessage)
        user_input = ""
        system_prompt = ""

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_prompt = msg.content
            elif isinstance(msg, HumanMessage):
                user_input = msg.content

        if not user_input:
            logger.warning("[LLM Adapter] No user input found")
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="Sorry, I didn't receive your message."))]
            )

        # Set system prompt
        if system_prompt:
            self.llm_service.set_system_prompt(system_prompt)

        # Call existing LLM service's streaming interface
        chunks = []
        full_response = ""

        try:
            stream = self.llm_service.chat_stream(user_input)
            if inspect.isawaitable(stream):
                response = await stream
                if response:
                    full_response = str(response)
            else:
                async for chunk in stream:
                    chunks.append(chunk)
                    full_response += chunk

                    # Notify callback (supports streaming output)
                    if run_manager:
                        await run_manager.on_llm_new_token(chunk)

        except Exception as e:
            logger.error(f"[LLM Adapter] Generation failed: {e}")
            full_response = f"Error generating response: {str(e)}"

        # Build AI message
        ai_message = AIMessage(content=full_response)

        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool],
        **kwargs: Any,
    ) -> LLMChatModelAdapter:
        """
        Bind tools (placeholder method; actual tool calls are handled by llm_node.py)
        """
        logger.info(f"[LLM Adapter bind_tools] called, tools count: {len(tools)}")

        # Directly set bound_tools
        self.bound_tools = list(tools)

        logger.info(f"[LLM Adapter bind_tools] set {len(self.bound_tools)} tools")
        for i, tool in enumerate(self.bound_tools):
            logger.debug(f"[LLM Adapter bind_tools] tool[{i}]: {tool.name}")

        return self


def create_chat_model_from_service(
    llm_service: LLMInterface,
    enable_tooling: bool = False,
    _enable_tooling: bool | None = None,
) -> BaseChatModel:
    """
    Create a LangChain ChatModel from an existing LLM service

    Args:
        llm_service: Existing LLM service instance
        enable_tooling: Whether to enable tool call support (placeholder; actual handling by llm_node.py)
        _enable_tooling: Backward-compatible alias for older callers.

    Returns:
        BaseChatModel: LangChain ChatModel instance
    """
    if _enable_tooling is not None:
        enable_tooling = _enable_tooling
    _ = enable_tooling

    # Dynamic proxies (e.g. TracingProxy) wrap LLMInterface for OTel tracing
    # but fail Pydantic's strict isinstance(LLMInterface) check in
    # LLMChatModelAdapter.  Unwrap before passing to the adapter.
    if hasattr(llm_service, "_target"):
        llm_service = llm_service._target

    model_name = "unknown"
    if hasattr(llm_service, "config") and hasattr(llm_service.config, "model"):
        model_name = llm_service.config.model
    elif hasattr(llm_service, "config") and hasattr(llm_service.config, "type"):
        model_name = llm_service.config.type

    return LLMChatModelAdapter(llm_service=llm_service, model_name=model_name)
