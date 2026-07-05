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

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "persona": self.persona,
            "refreshed": list(self.refreshed),
            "error": _redact(self.error) if self.error else None,
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
            persona = PersonaConfig.load(next_config.persona, personas_dir=self.personas_dir)
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


def _unwrap_service_proxy(service: Any) -> Any:
    """Return the wrapped service object when passed a tracing proxy."""
    try:
        return object.__getattribute__(service, "_target")
    except AttributeError:
        return service
