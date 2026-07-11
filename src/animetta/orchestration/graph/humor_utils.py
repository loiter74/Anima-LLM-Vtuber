"""Shared helpers for Humor Agent graph nodes."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from animetta.services.humor import HumorConfig


def get_config_value(config: RunnableConfig | None, key: str, default: Any = None) -> Any:
    """Get a configurable value from LangGraph config."""
    if config:
        return config.get("configurable", {}).get(key, default)
    return default


def get_service_context(config: RunnableConfig | None) -> Any | None:
    """Get service_context from LangGraph config."""
    return get_config_value(config, "service_context")


def resolve_humor_config(config: RunnableConfig | None, service_context: Any) -> HumorConfig:
    """Resolve Humor Agent config from RunnableConfig or AppConfig."""
    explicit = get_config_value(config, "humor_config", None)
    if isinstance(explicit, HumorConfig):
        return explicit
    if isinstance(explicit, dict):
        return HumorConfig.model_validate(explicit)

    app_config = getattr(service_context, "config", None)
    app_humor = getattr(app_config, "humor", None) if app_config is not None else None
    if isinstance(app_humor, HumorConfig):
        return app_humor
    if isinstance(app_humor, dict):
        return HumorConfig.model_validate(app_humor)
    return HumorConfig()
