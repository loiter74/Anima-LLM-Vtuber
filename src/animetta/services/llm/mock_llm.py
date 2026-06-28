"""
Mock LLM implementation - for testing and development
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.llm import MockLLMConfig

from .interface import LLMInterface


@ProviderRegistry.register_service("llm", "mock")
class MockLLM(LLMInterface):
    """
    Mock LLM implementation
    Does not call an actual LLM, returns fixed mock responses

    Features:
    - Registered via @ProviderRegistry.register_service
    - Supports from_config to create instances from configuration
    """

    # Class-level attribute: supported config type
    config_class = MockLLMConfig

    def __init__(self, system_prompt: str = ""):
        self.system_prompt = system_prompt
        self.history: list[dict[str, Any]] = []
        self.call_count = 0
        self.instance_id = str(uuid.uuid4())[:8]

    @classmethod
    def from_config(cls, config: LLMBaseConfig, system_prompt: str = "", **kwargs) -> MockLLM:
        """
        Create an instance from a configuration object

        Args:
            config: LLM config object
            system_prompt: System prompt
            **kwargs: Additional parameters (ignored)

        Returns:
            MockLLM instance
        """
        # Mock does not require any fields from config
        instance = cls(system_prompt=system_prompt)
        logger.info(f"[MockLLM-{instance.instance_id}] Initialization complete")
        return instance

    async def chat(
        self,
        user_input: str,
        **kwargs
    ) -> str:
        """Return a mock response"""
        # Call count
        self.call_count += 1
        call_id = f"{self.instance_id}-{self.call_count}"

        # Log call start
        start_time = time.time()
        input_length = len(user_input)
        history_length = len(self.history)

        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")
        logger.info(f"[MockLLM:{call_id}] 🔵 Starting call (mock mode)")
        logger.info(f"[MockLLM:{call_id}] Input: {user_input[:100]}{'...' if input_length > 100 else ''} (length: {input_length})")
        logger.info(f"[MockLLM:{call_id}] History rounds: {history_length // 2}")

        # Simulate processing delay
        import asyncio
        await asyncio.sleep(0.1)

        # Record to history
        self.history.append({"role": "user", "content": user_input})

        # Generate mock response
        responses = [
            f"这是第 {self.call_count} 条模拟回复。你刚才说的是：「{user_input}」",
            f"收到你的消息：「{user_input}」。我是一个 Mock LLM，用于测试和开发。",
            f"你好！你说的是：「{user_input}」。有什么我可以帮助你的吗？",
        ]
        response = responses[self.call_count % len(responses)]

        # Record response to history
        self.history.append({"role": "assistant", "content": response})

        # Calculate elapsed time
        elapsed_time = time.time() - start_time
        output_length = len(response)

        logger.info(f"[MockLLM:{call_id}] 🟢 Call successful")
        logger.info(f"[MockLLM:{call_id}] Elapsed: {elapsed_time:.2f}s")
        logger.info(f"[MockLLM:{call_id}] Output: {response[:100]}{'...' if output_length > 100 else ''} (length: {output_length})")
        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")

        return response

    async def chat_stream(
        self,
        user_input: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream mock response"""
        # Call count
        self.call_count += 1
        call_id = f"{self.instance_id}-{self.call_count}"

        # Log call start
        start_time = time.time()
        input_length = len(user_input)

        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")
        logger.info(f"[MockLLM:{call_id}] 🔵 Starting streaming call (mock mode)")
        logger.info(f"[MockLLM:{call_id}] Input: {user_input[:100]}{'...' if input_length > 100 else ''}")

        response = await self.chat(user_input, **kwargs)

        # Simulate streaming output
        chunk_count = 0
        for char in response:
            chunk_count += 1
            yield char

        # Calculate elapsed time
        elapsed_time = time.time() - start_time

        logger.info(f"[MockLLM:{call_id}] 🟢 Streaming call successful")
        logger.info(f"[MockLLM:{call_id}] Elapsed: {elapsed_time:.2f}s")
        logger.info(f"[MockLLM:{call_id}] Chunks: {chunk_count}")
        logger.info(f"[MockLLM:{call_id}] ═══════════════════════════════════")

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt"""
        self.system_prompt = prompt

    def get_history(self) -> list[dict[str, Any]]:
        """Get conversation history"""
        return self.history.copy()

    def clear_history(self) -> None:
        """Clear conversation history"""
        self.history = []
        self.call_count = 0

    async def close(self) -> None:
        """No resources to clean up"""
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        """
        Handle user interruption

        Args:
            heard_response: Partial response heard by the user
        """
        if heard_response and self.history and self.history[-1].get("role") == "user":
            # Save partial response to history
            self.history.append({
                "role": "assistant",
                "content": heard_response
            })
            self.history.append({
                "role": "system",
                "content": "[用户打断了对话]"
            })

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
        # Mock implementation: no-op
        pass
