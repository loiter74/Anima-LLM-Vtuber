"""Compatibility facade for runtime reload APIs; remove after one release."""

from animetta.config.runtime_reloader import (
    ReloadResult,
    RuntimeConfigReloader,
    classify_effective_config_diff,
)
from animetta.services.runtime_config import (
    RuntimeConfigApplyResult,
    RuntimePrompt,
    apply_lightweight_llm_config,
    apply_runtime_config_to_contexts,
    apply_runtime_llm_config,
    build_live2d_prompt,
    build_runtime_system_prompt,
)

__all__ = [
    "ReloadResult",
    "RuntimeConfigApplyResult",
    "RuntimeConfigReloader",
    "RuntimePrompt",
    "apply_lightweight_llm_config",
    "apply_runtime_config_to_contexts",
    "apply_runtime_llm_config",
    "build_live2d_prompt",
    "build_runtime_system_prompt",
    "classify_effective_config_diff",
]
