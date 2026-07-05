"""
LLM service factory - automatically creates LLM service instances based on configuration
"""

from __future__ import annotations

from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.llm import (
    GLMLLMConfig,
    MockLLMConfig,
    OllamaLLMConfig,
    OpenAILLMConfig,
)
from animetta.tracing.proxy import TracingProxy

from .interface import LLMInterface


class LLMFactory:
    """
    LLM service factory class (simplified version)

    Uses ProviderRegistry to automatically find and instantiate services,
    eliminating the need to manually maintain if-elif chains.

    To add a new provider, simply:
    1. Create a config class and register it
    2. Create a service class and register it
    No modifications to the factory code are required.
    """

    @staticmethod
    def create_from_config(config: LLMConfig, system_prompt: str = "") -> LLMInterface:
        """
        Automatically create an LLM service instance from a config object

        Args:
            config: LLM config object (Discriminated Union)
            system_prompt: System prompt

        Returns:
            LLMInterface: LLM service instance

        Raises:
            ValueError: If no matching service implementation is found
        """
        logger.debug(f"create_from_config: config.type={config.type}, config class={type(config).__name__}")

        try:
            # Use Registry to automatically find and instantiate
            llm = ProviderRegistry.create_service("llm", config, system_prompt=system_prompt)
            logger.info(f"LLM service created successfully: type={config.type}, instance={type(llm).__name__}")
            return TracingProxy(llm, service_name="llm")
        except Exception as e:
            # Catch all exceptions (ValueError, TypeError, ImportError, ConnectionError, etc.)
            logger.error(f"Failed to create LLM service (type={config.type}): {type(e).__name__}: {e}")
            # Fall back to Mock implementation
            logger.warning(f"Falling back to MockLLM (original config: {config.type})")
            from .mock_llm import MockLLM
            return MockLLM(system_prompt=system_prompt)

    @staticmethod
    def create(provider: str, system_prompt: str = "", **kwargs) -> LLMInterface:
        """
        Create an LLM service instance by provider name (backward compatible)

        Args:
            provider: Provider name
            system_prompt: System prompt
            **kwargs: Parameters passed to the concrete implementation

        Returns:
            LLMInterface: LLM service instance
        """

        # Build config object based on provider name
        config_map = {
            "openai": lambda: OpenAILLMConfig(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "gpt-4o-mini"),
                base_url=kwargs.get("base_url"),
                temperature=kwargs.get("temperature", 0.7),
                top_p=kwargs.get("top_p", 0.9),
                max_tokens=kwargs.get("max_tokens", 1000)
            ),
            "glm": lambda: GLMLLMConfig(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model", "glm-4-flash"),
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096),
                enable_thinking=kwargs.get("enable_thinking", False)
            ),
            "ollama": lambda: OllamaLLMConfig(
                model=kwargs.get("model", "llama3"),
                base_url=kwargs.get("base_url", "http://localhost:11434"),
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096)
            ),
            "mock": lambda: MockLLMConfig(),
        }

        config_factory = config_map.get(provider)
        if config_factory is None:
            logger.warning(f"Unknown LLM provider: {provider}, using Mock implementation")
            config = MockLLMConfig()
        else:
            config = config_factory()

        return LLMFactory.create_from_config(config, system_prompt)

    @staticmethod
    def get_available_configs() -> list:
        """Get the list of all available providers"""
        return ProviderRegistry.list_services("llm")
