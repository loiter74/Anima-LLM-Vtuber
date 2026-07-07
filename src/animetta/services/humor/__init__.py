"""Humor Agent service package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import HumorAgent
    from .config import DEFAULT_ALLOWED_STYLES, DEFAULT_WORLDVIEW_HINTS, HumorConfig
    from .models import (
        HumorFallbackReason,
        HumorRewriteRequest,
        HumorRewriteResult,
        InternalLLMCallResult,
    )

__all__ = [
    "DEFAULT_ALLOWED_STYLES",
    "DEFAULT_WORLDVIEW_HINTS",
    "HumorAgent",
    "HumorConfig",
    "HumorFallbackReason",
    "HumorRewriteRequest",
    "HumorRewriteResult",
    "InternalLLMCallResult",
]


def __getattr__(name: str):
    if name == "HumorAgent":
        from .agent import HumorAgent

        return HumorAgent
    if name in {"DEFAULT_ALLOWED_STYLES", "DEFAULT_WORLDVIEW_HINTS", "HumorConfig"}:
        from . import config

        return getattr(config, name)
    if name in {
        "HumorFallbackReason",
        "HumorRewriteRequest",
        "HumorRewriteResult",
        "InternalLLMCallResult",
    }:
        from . import models

        return getattr(models, name)
    raise AttributeError(name)
