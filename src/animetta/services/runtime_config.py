"""Apply reload-safe runtime settings to active service contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from animetta.config.runtime_reloader import redact_runtime_diagnostic
from animetta.observability.service_proxy import unwrap_service_proxy


@dataclass(frozen=True)
class RuntimePrompt:
    """Effective runtime prompt plus non-fatal build diagnostics."""

    system_prompt: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeConfigApplyResult:
    """Metadata returned after applying runtime config to active contexts."""

    version: int
    persona: str
    sessions: int
    effective_hash: str = ""
    semantic_hash: str = ""
    prompt_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "persona": self.persona,
            "sessions": self.sessions,
            "effective_hash": self.effective_hash,
            "semantic_hash": self.semantic_hash,
            "prompt_warnings": list(self.prompt_warnings),
        }


def apply_lightweight_llm_config(llm_engine: Any, llm_config: Any) -> None:
    """Apply reload-safe scalar fields to an existing LLM engine."""
    if llm_engine is None or llm_config is None:
        return
    target = unwrap_service_proxy(llm_engine)
    for name in ("temperature", "top_p", "max_tokens"):
        if hasattr(llm_config, name) and hasattr(target, name):
            setattr(target, name, getattr(llm_config, name))
    thinking = getattr(llm_config, "thinking", None)
    if thinking and hasattr(target, "extra_body"):
        setattr(target, "extra_body", {"thinking": {"type": thinking}})


def build_runtime_system_prompt(config: Any) -> RuntimePrompt:
    """Build the system prompt from the active immutable runtime snapshot."""
    if config is None:
        return RuntimePrompt(system_prompt="", warnings=[])

    live2d_prompt, warnings = build_live2d_prompt()
    try:
        prompt = config.get_system_prompt(live2d_prompt=live2d_prompt)
    except TypeError:
        prompt = config.get_system_prompt()
    if not isinstance(prompt, str):
        warnings.append(
            f"Runtime system prompt unavailable: expected str, got {type(prompt).__name__}"
        )
        prompt = ""
    return RuntimePrompt(system_prompt=prompt, warnings=warnings)


def build_live2d_prompt() -> tuple[str | None, list[str]]:
    """Build the Live2D prompt fragment, returning warnings instead of raising."""
    try:
        from animetta.avatar.prompts import PerformancePromptBuilder
        from animetta.config.live2d import get_live2d_config

        live2d_config = get_live2d_config()
        if live2d_config is None or not getattr(live2d_config, "enabled", False):
            return None, []

        return PerformancePromptBuilder().build_prompt(), []
    except Exception as exc:
        warning = f"Live2D prompt unavailable: {redact_runtime_diagnostic(str(exc))}"
        logger.warning("[RuntimePrompt] {}", warning)
        return None, [warning]


def apply_runtime_llm_config(
    llm_engine: Any,
    llm_config: Any,
    system_prompt: str | None = None,
) -> None:
    """Apply reload-safe LLM fields and prompt to an existing engine."""
    if llm_engine is None:
        return

    apply_lightweight_llm_config(llm_engine, llm_config)
    if system_prompt is None:
        return

    target = unwrap_service_proxy(llm_engine)
    set_prompt = getattr(target, "set_system_prompt", None)
    if callable(set_prompt):
        set_prompt(system_prompt)
    elif hasattr(target, "system_prompt"):
        setattr(target, "system_prompt", system_prompt)


def apply_runtime_config_to_contexts(
    config: Any,
    version: int,
    contexts: Any,
    *,
    runtime_prompt: RuntimePrompt | None = None,
) -> RuntimeConfigApplyResult:
    """Apply a validated runtime config to active session contexts."""
    runtime_prompt = runtime_prompt or build_runtime_system_prompt(config)
    llm_config = config.agent.llm_config if getattr(config, "agent", None) else None
    sessions = 0

    for ctx in contexts:
        ctx.config = config
        ctx.runtime_config_version = version
        ctx.runtime_config_hash = getattr(config, "effective_hash", "")
        ctx.runtime_semantic_hash = getattr(config, "semantic_hash", "")
        apply_runtime_llm_config(
            getattr(ctx, "llm_engine", None),
            llm_config,
            runtime_prompt.system_prompt,
        )
        sessions += 1

    return RuntimeConfigApplyResult(
        version=version,
        persona=getattr(config, "persona", ""),
        sessions=sessions,
        effective_hash=getattr(config, "effective_hash", ""),
        semantic_hash=getattr(config, "semantic_hash", ""),
        prompt_warnings=runtime_prompt.warnings,
    )


__all__ = [
    "RuntimeConfigApplyResult",
    "RuntimePrompt",
    "apply_lightweight_llm_config",
    "apply_runtime_config_to_contexts",
    "apply_runtime_llm_config",
    "build_live2d_prompt",
    "build_runtime_system_prompt",
]
