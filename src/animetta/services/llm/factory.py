"""
LLM service factory - automatically creates LLM service instances based on configuration
"""

from __future__ import annotations

from importlib import import_module

from loguru import logger

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.llm import (
    GLMLLMConfig,
    MockLLMConfig,
    OllamaLLMConfig,
    OpenAILLMConfig,
)
from animetta.core.readiness import unwrap_tracing_proxy
from animetta.observability.ports import ObservationRecorder
from animetta.observability.service_proxy import instrument_service

from .interface import LLMInterface

_AVAILABLE_LLM_PROVIDERS = (
    "mock",
    "glm",
    "ollama",
    "openai",
    "deepseek",
    "local_lora",
)


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
    def create_from_config(
        config: LLMConfig,
        system_prompt: str = "",
        *,
        strict: bool = False,
        observation_recorder: ObservationRecorder | None = None,
    ) -> LLMInterface:
        """
        Automatically create an LLM service instance from a config object

        Args:
            config: LLM config object (Discriminated Union)
            system_prompt: System prompt
            strict: Propagate creation failures instead of substituting MockLLM

        Returns:
            LLMInterface: LLM service instance

        Raises:
            ValueError: If no matching service implementation is found
        """
        logger.debug(f"create_from_config: config.type={config.type}, config class={type(config).__name__}")

        try:
            module_name = {
                "mock": ".mock_llm",
                "glm": ".glm_llm",
                "ollama": ".ollama_llm",
                "openai": ".openai_llm",
                "deepseek": ".openai_llm",
                "local_lora": ".local_lora_llm",
            }.get(config.type)
            if module_name is not None:
                try:
                    import_module(module_name, __package__)
                except ImportError as exc:
                    if strict:
                        raise
                    logger.warning(
                        "LLM provider import unavailable: "
                        f"type={config.type}, error={type(exc).__name__}"
                    )
            # Use Registry to automatically find and instantiate
            llm = ProviderRegistry.create_service("llm", config, system_prompt=system_prompt)
            concrete = unwrap_tracing_proxy(llm)

            if config.type in {"openai", "deepseek"}:
                from .openai_llm import OpenAILLM

                if isinstance(concrete, OpenAILLM):
                    concrete._bind_provider_identity(config.type)
            if strict and config.type != "mock":
                from .mock_llm import MockLLM

                if isinstance(concrete, MockLLM):
                    raise RuntimeError(
                        "Strict LLM provider creation returned MockLLM "
                        "for a non-mock config"
                    )
            logger.info(f"LLM service created successfully: type={config.type}, instance={type(llm).__name__}")
            return instrument_service(
                llm,
                observation_recorder,
                "llm",
                provider=config.type,
                model=getattr(config, "model", None),
            )
        except Exception as e:
            if strict:
                logger.error(
                    "Strict LLM service creation failed: "
                    f"type={config.type}, error={type(e).__name__}"
                )
                raise
            # Catch all exceptions (ValueError, TypeError, ImportError, ConnectionError, etc.)
            logger.error(
                "Failed to create LLM service: "
                f"type={config.type}, error={type(e).__name__}"
            )
            # Fall back to Mock implementation
            logger.warning(f"Falling back to MockLLM (original config: {config.type})")
            from .mock_llm import MockLLM
            return instrument_service(
                MockLLM(system_prompt=system_prompt),
                observation_recorder,
                "llm",
                provider="mock",
                model="mock",
            )

    @staticmethod
    def create(
        provider: str,
        system_prompt: str = "",
        *,
        strict: bool = False,
        observation_recorder: ObservationRecorder | None = None,
        **kwargs,
    ) -> LLMInterface:
        """
        Create an LLM service instance by provider name (backward compatible)

        Args:
            provider: Provider name
            system_prompt: System prompt
            strict: Reject unknown providers and propagate creation failures
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
            if strict:
                raise ValueError(f"Unknown LLM provider: {provider}")
            logger.warning(f"Unknown LLM provider: {provider}, using Mock implementation")
            config = MockLLMConfig()
        else:
            config = config_factory()

        return LLMFactory.create_from_config(
            config,
            system_prompt,
            strict=strict,
            observation_recorder=observation_recorder,
        )

    @staticmethod
    def get_available_configs() -> list:
        """Get the stable catalog of providers with service implementations."""
        return list(_AVAILABLE_LLM_PROVIDERS)
