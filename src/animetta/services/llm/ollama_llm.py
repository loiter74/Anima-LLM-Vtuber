from __future__ import annotations

"""
Ollama LLM implementation
Uses the ollama SDK to call local Ollama models

"""

from collections.abc import AsyncIterator
from typing import Any

import ollama
from loguru import logger

from animetta.config.core.registry import ProviderRegistry

from .interface import LLMInterface


@ProviderRegistry.register_service("llm", "ollama")
class OllamaLLM(LLMInterface):
    """
    Ollama local model Agent implementation

    Uses the ollama SDK to call locally running LLaMA, Mistral, and other models
    Supports streaming output
    """

    def __init__(
        self,
        model: str = "llama3",
        system_prompt: str = "",
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs
    ):
        """
        Initialize Ollama LLM

        Args:
            model: Model name (llama3, mistral, qwen, etc.)
            system_prompt: System prompt
            base_url: Ollama service address (default http://localhost:11434)
            temperature: Temperature parameter
            max_tokens: Maximum number of tokens to generate
        """
        self.model = model
        self.system_prompt = system_prompt
        self.base_url = base_url or "http://localhost:11434"
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Conversation history
        self.history: list[dict[str, str]] = []

        # Initialize client
        client_kwargs = {"host": self.base_url}
        self.client = ollama.Client(**client_kwargs)

        logger.info(f"OllamaLLM initialized: model={model}, base_url={self.base_url}")

    @classmethod
    def from_config(cls, config: LLMBaseConfig, system_prompt: str = "", **kwargs) -> OllamaLLM:
        """
        Create an instance from a configuration object

        Args:
            config: OllamaLLMConfig configuration object
            system_prompt: System prompt
            **kwargs: Additional parameters (ignored)

        Returns:
            OllamaLLM instance

        Raises:
            TypeError: If the config type does not match
        """
        if not isinstance(config, OllamaLLMConfig):
            raise TypeError(f"OllamaLLM 需要 OllamaLLMConfig，收到: {type(config)}")

        return cls(
            model=config.model,
            system_prompt=system_prompt,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens
        )

    def _build_messages(self, user_input: str) -> list[dict[str, str]]:
        """
        Build messages list

        Args:
            user_input: User input

        Returns:
            List[Dict[str, str]]: Complete messages list
        """
        messages = []

        # Add system prompt
        if self.system_prompt:
            messages.append({
                "role": "system",
                "content": self.system_prompt
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
        Chat with the Ollama model

        Args:
            user_input: User input
            **kwargs: Additional parameters

        Returns:
            str: Model response
        """
        messages = self._build_messages(user_input)

        try:
            # ollama SDK is synchronous, needs to run in thread pool
            import asyncio
            loop = asyncio.get_running_loop()

            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat(
                    model=kwargs.get("model", self.model),
                    messages=messages,
                    options={
                        "temperature": kwargs.get("temperature", self.temperature),
                        "num_predict": kwargs.get("max_tokens", self.max_tokens)
                    }
                )
            )

            assistant_message = response["message"]["content"]

            # Update history
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": assistant_message})

            logger.debug(f"Ollama response: {assistant_message[:100]}...")
            return assistant_message

        except Exception as e:
            logger.error(f"Ollama chat error: {e}")
            raise

    async def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        """
        Streaming chat

        Args:
            user_input: User input
            **kwargs: Additional parameters

        Yields:
            str: Text chunk of the model response
        """
        messages = self._build_messages(user_input)

        full_response = ""

        try:
            import asyncio
            loop = asyncio.get_running_loop()

            # Run sync streaming call in thread pool
            def sync_stream():
                return self.client.chat(
                    model=kwargs.get("model", self.model),
                    messages=messages,
                    stream=True,
                    options={
                        "temperature": kwargs.get("temperature", self.temperature),
                        "num_predict": kwargs.get("max_tokens", self.max_tokens)
                    }
                )

            stream = await loop.run_in_executor(None, sync_stream)

            for chunk in stream:
                if "message" in chunk and "content" in chunk["message"]:
                    content = chunk["message"]["content"]
                    full_response += content
                    yield content

            # Update history
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": full_response})

        except Exception as e:
            logger.error(f"Ollama streaming chat error: {e}")
            raise

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
        # Ollama client does not need explicit closing
        logger.info("OllamaLLM resources released")
