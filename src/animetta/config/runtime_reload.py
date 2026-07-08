"""Runtime config reload support for persona and lightweight LLM settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from animetta.config.app import AppConfig, clear_config_caches
from animetta.config.persona.base import PersonaConfig


@dataclass
class ReloadResult:
    """Structured result returned by a runtime config reload attempt."""

    ok: bool
    version: int
    persona: str
    refreshed: list[str] = field(default_factory=list)
    error: str | None = None
    preserved: bool = False
    applied: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "persona": self.persona,
            "refreshed": list(self.refreshed),
            "error": _redact(self.error) if self.error else None,
            "preserved": self.preserved,
            "applied": dict(self.applied),
        }


@dataclass(frozen=True)
class RuntimePrompt:
    """Effective runtime prompt plus non-fatal build diagnostics."""

    system_prompt: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeConfigApplyResult:
    """Metadata returned after applying a runtime config to active contexts."""

    version: int
    persona: str
    sessions: int
    prompt_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "persona": self.persona,
            "sessions": self.sessions,
            "prompt_warnings": list(self.prompt_warnings),
        }


class RuntimeConfigReloader:
    """Validate and swap lightweight runtime configuration atomically."""

    def __init__(
        self,
        config: AppConfig,
        *,
        config_path: str | None = None,
        personas_dir: str | None = None,
        version: int = 1,
    ) -> None:
        self._config = config
        self.config_path = config_path
        self.personas_dir = personas_dir
        self.version = version

    @property
    def config(self) -> AppConfig:
        return self._config

    def reload(self) -> ReloadResult:
        """Reload config from disk, preserving the previous config on failure."""
        try:
            clear_config_caches()
            next_config = AppConfig.load(self.config_path)
            persona = PersonaConfig.load(
                next_config.persona,
                personas_dir=self.personas_dir,
                strict=True,
            )
            next_config._persona = persona

            self.version += 1
            self._config = next_config
            logger.info(
                "[RuntimeConfigReload] Reloaded config: persona={}, version={}",
                next_config.persona,
                self.version,
            )
            return ReloadResult(
                ok=True,
                version=self.version,
                persona=next_config.persona,
                refreshed=["persona", "llm"],
            )
        except Exception as exc:
            logger.warning("[RuntimeConfigReload] Reload failed: {}", _redact(str(exc)))
            return ReloadResult(
                ok=False,
                version=self.version,
                persona=self._config.persona,
                refreshed=[],
                error=str(exc),
                preserved=True,
            )


def _redact(value: str | None) -> str | None:
    """Redact likely secret tokens from diagnostic text."""
    if value is None:
        return None
    import re

    return re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", value)


def apply_lightweight_llm_config(llm_engine: Any, llm_config: Any) -> None:
    """Apply lightweight LLM runtime fields to an existing engine."""
    if llm_engine is None or llm_config is None:
        return
    target = _unwrap_service_proxy(llm_engine)
    for name in ("model", "temperature", "top_p", "max_tokens"):
        if hasattr(llm_config, name) and hasattr(target, name):
            setattr(target, name, getattr(llm_config, name))
    thinking = getattr(llm_config, "thinking", None)
    if thinking and hasattr(target, "extra_body"):
        setattr(target, "extra_body", {"thinking": {"type": thinking}})


def build_runtime_system_prompt(config: Any) -> RuntimePrompt:
    """Build the effective runtime system prompt from the active AppConfig."""
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
        from animetta.avatar.prompts import EmotionPromptBuilder
        from animetta.config.live2d import get_live2d_config

        live2d_config = get_live2d_config()
        if live2d_config is None or not getattr(live2d_config, "enabled", False):
            return None, []

        builder = EmotionPromptBuilder.from_config(
            {"valid_emotions": list(getattr(live2d_config, "valid_emotions", []) or [])}
        )
        return builder.build_prompt(), []
    except Exception as exc:
        warning = f"Live2D prompt unavailable: {_redact(str(exc))}"
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

    target = _unwrap_service_proxy(llm_engine)
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
        prompt_warnings=runtime_prompt.warnings,
    )


def _unwrap_service_proxy(service: Any) -> Any:
    """Return the wrapped service object when passed a tracing proxy."""
    try:
        return object.__getattribute__(service, "_target")
    except AttributeError:
        return service
