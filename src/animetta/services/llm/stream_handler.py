from __future__ import annotations

"""
OpenAI LLM stream handler — handles streaming chat logic.

Extracted from openai_llm.py to separate streaming concerns from
core LLM implementation.
"""

import contextlib
import time as time_module
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from .openai_llm import OpenAILLM


class OpenAIStreamHandler:
    """
    Handles streaming chat for OpenAILLM.

    Encapsulates the chat_stream logic: building messages, iterating
    stream chunks, accumulating full response, recording usage metrics,
    and updating conversation history.
    """

    def __init__(self, llm_instance: OpenAILLM):
        """
        Args:
            llm_instance: The OpenAILLM instance that owns this handler.
        """
        self.llm = llm_instance

    async def stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        """
        Streaming chat

        Args:
            user_input: User input
            **kwargs: Supports system_prompt — dynamically overrides the system prompt (RAG memory enhancement)

        Yields:
            str: Text chunk of the model response
        """
        system_prompt = kwargs.get("system_prompt")
        messages = self.llm._build_messages(user_input, system_prompt=system_prompt)

        full_response = ""
        t_start = time_module.perf_counter()

        try:
            response = await self.llm.client.chat.completions.create(
                model=kwargs.get("model", self.llm.model),
                messages=messages,
                temperature=kwargs.get("temperature", self.llm.temperature),
                top_p=kwargs.get("top_p", self.llm.top_p),
                max_tokens=kwargs.get("max_tokens", self.llm.max_tokens),
                stream=True,
                stream_options={"include_usage": True},
                **({"extra_body": self.llm.extra_body} if self.llm.extra_body else {}),
            )

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content
                # Final chunk may contain usage info
                if hasattr(chunk, "usage") and chunk.usage:
                    with contextlib.suppress(AttributeError):
                        # Mock response objects (e.g. async generators) may not support attribute assignment
                        response._usage = chunk.usage

            # OTel metrics: record usage from stream
            duration_s = time_module.perf_counter() - t_start
            try:
                # Try to get usage from response object or estimate from text
                if hasattr(response, "_usage") and response._usage:
                    input_tokens = getattr(response._usage, "prompt_tokens", 0)
                    output_tokens = getattr(response._usage, "completion_tokens", 0)
                else:
                    # Fallback: rough estimate (4 chars ≈ 1 token)
                    input_tokens = len(user_input) // 4
                    output_tokens = len(full_response) // 4
                # Use a synthetic response-like object for _record_usage
                class _StreamUsage:
                    pass
                usage_obj = _StreamUsage()
                usage_obj.usage = _StreamUsage()
                usage_obj.usage.prompt_tokens = input_tokens
                usage_obj.usage.completion_tokens = output_tokens
                self.llm._record_usage(usage_obj, duration_s)
            except Exception:
                pass

            # Update history
            self.llm.history.append({"role": "user", "content": user_input})
            self.llm.history.append({"role": "assistant", "content": full_response})

        except Exception as e:
            duration_s = time_module.perf_counter() - t_start
            self.llm._record_error(duration_s)
            logger.exception(f"OpenAI streaming chat error: {type(e).__name__}: {e}")
            raise
