"""Provider registry — plugin-based configuration and service registration."""

from __future__ import annotations

from typing import Annotated, Union

from loguru import logger
from pydantic import Field

from .base import ProviderConfig


class ProviderRegistry:
    """Provider registry managing config classes and service classes.

    Supports dynamic category registration — no hardcoded category limits.
    Categories are created automatically on first register_config() call.

    Example:
        @ProviderRegistry.register_config("llm", "openai")
        class OpenAILLMConfig(LLMBaseConfig):
            type: Literal["openai"] = "openai"

        @ProviderRegistry.register_service("llm", "openai")
        class OpenAIAgent(AgentInterface):
            @classmethod
            def from_config(cls, config: OpenAILLMConfig) -> "OpenAIAgent":
                return cls(api_key=config.api_key, ...)
    """

    # Config class storage: {"llm": {"openai": OpenAILLMConfig, ...}, ...}
    _configs: dict[str, dict[str, type[ProviderConfig]]] = {}

    # Service class storage: {"llm": {"openai": OpenAIAgent, ...}, ...}
    _services: dict[str, dict[str, type]] = {}

    # ==================== Config Class Registration ====================

    @classmethod
    def register_config(cls, category: str, provider_type: str):
        """Decorator: Register a provider configuration class.

        Creates the category slot dynamically if it doesn't exist —
        no hardcoded category limits.

        Args:
            category: Provider category (e.g., "llm", "asr", "tts", "vc", "separation")
            provider_type: Provider type identifier (e.g., "openai", "glm", "silero")

        Returns:
            Decorator function
        """
        def decorator(config_class: type[ProviderConfig]) -> type[ProviderConfig]:
            cls._configs.setdefault(category, {})[provider_type] = config_class
            logger.debug(f"Registered config class: {category}.{provider_type} -> {config_class.__name__}")
            return config_class
        return decorator

    # ==================== Service Class Registration ====================

    @classmethod
    def register_service(cls, category: str, provider_type: str):
        """Decorator: Register a service implementation class.

        Args:
            category: Provider category
            provider_type: Provider type identifier (must match config class)

        Returns:
            Decorator function
        """
        def decorator(service_class: type) -> type:
            cls._services.setdefault(category, {})[provider_type] = service_class
            logger.debug(f"Registered service class: {category}.{provider_type} -> {service_class.__name__}")
            return service_class
        return decorator

    # ==================== Config Class Access ====================

    @classmethod
    def get_config(cls, category: str, provider_type: str) -> type[ProviderConfig] | None:
        """Get a registered provider configuration class.

        Args:
            category: Provider category
            provider_type: Provider type identifier

        Returns:
            Configuration class, or None if not registered
        """
        return cls._configs.get(category, {}).get(provider_type)

    @classmethod
    def list_configs(cls, category: str) -> list[str]:
        """List all registered configuration class names for a category.

        Args:
            category: Provider category

        Returns:
            List of provider type identifiers
        """
        return list(cls._configs.get(category, {}).keys())

    @classmethod
    def get_all_configs(cls) -> dict[str, dict[str, type[ProviderConfig]]]:
        """Get all registered configuration classes.

        Returns:
            Nested dictionary of all registered config classes
        """
        return {k: v.copy() for k, v in cls._configs.items()}

    # ==================== Service Class Access ====================

    @classmethod
    def get_service_class(cls, category: str, provider_type: str) -> type | None:
        """Get a registered service implementation class.

        Args:
            category: Provider category
            provider_type: Provider type identifier

        Returns:
            Service class, or None if not registered
        """
        return cls._services.get(category, {}).get(provider_type)

    @classmethod
    def create_service(cls, category: str, config: ProviderConfig, **extra_kwargs):
        """Automatically create a service instance from configuration.

        Args:
            category: Provider category
            config: Configuration object (contains type field)
            **extra_kwargs: Extra arguments (e.g., system_prompt)

        Returns:
            Service instance

        Raises:
            ValueError: If no matching service class is found
        """
        provider_type = config.type
        service_class = cls.get_service_class(category, provider_type)

        if service_class is None:
            raise ValueError(
                f"Service implementation not found: {category}.{provider_type}. "
                f"Available services: {cls.list_services(category)}"
            )

        if hasattr(service_class, 'from_config'):
            return service_class.from_config(config, **extra_kwargs)
        else:
            raise ValueError(
                f"Service class {service_class.__name__} is missing the from_config class method"
            )

    @classmethod
    def list_services(cls, category: str) -> list[str]:
        """List all registered service class names for a category."""
        return list(cls._services.get(category, {}).keys())

    @classmethod
    def service_types_for_instance(cls, category: str, service: object) -> tuple[str, ...]:
        """Return registered provider types implemented by an actual instance."""
        return tuple(
            provider_type
            for provider_type, service_class in cls._services.get(category, {}).items()
            if isinstance(service, service_class)
        )

    # ==================== Union Type Factory ====================

    @classmethod
    def create_union_type(cls, category: str):
        """Dynamically create a Discriminated Union type from registered configs.

        Args:
            category: Provider category (any registered category)

        Returns:
            Annotated[Union[...], Field(discriminator="type")] type

        Raises:
            ValueError: If no providers registered for the category

        Usage:
            LLMConfig = ProviderRegistry.create_union_type("llm")
        """
        cat_configs = cls._configs.get(category, {})
        if not cat_configs:
            raise ValueError(f"No registered providers for category: {category}")

        classes = list(cat_configs.values())
        union_type = Union[tuple(classes)]  # type: ignore[valid-type]
        return Annotated[union_type, Field(discriminator="type")]

    # ==================== Lifecycle ====================

    @classmethod
    def clear(cls, category: str | None = None, *, clear_services: bool = False):
        """Clear registration data (mainly for testing).

        Args:
            category: Category to clear. If None, clears all.
            clear_services: If True, also clear registered services. Default False
                (clear only affects configs, preserving service registrations).
        """
        if category:
            cls._configs.pop(category, None)
            if clear_services:
                cls._services.pop(category, None)
        else:
            cls._configs.clear()
            if clear_services:
                cls._services.clear()
