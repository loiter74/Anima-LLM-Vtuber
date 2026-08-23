"""Pure config reload and diff classification for immutable runtime snapshots."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from animetta.config.manifest import (
    DEFAULT_MANIFEST_PATH,
    EffectiveConfig,
    load_effective_config,
)

_HOT_LLM_FIELDS = frozenset({"temperature", "top_p", "max_tokens", "thinking"})
_HOT_RUNTIME_FIELDS = frozenset({"enable_subtitle_translation", "enable_active_memes"})


@dataclass
class ReloadResult:
    """Structured result returned by a runtime config reload attempt."""

    ok: bool
    version: int
    persona: str
    refreshed: list[str] = field(default_factory=list)
    error: str | None = None
    preserved: bool = False
    effective_hash: str = ""
    semantic_hash: str = ""
    restart_required: list[str] = field(default_factory=list)
    applied: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "version": self.version,
            "persona": self.persona,
            "refreshed": list(self.refreshed),
            "error": redact_runtime_diagnostic(self.error) if self.error else None,
            "preserved": self.preserved,
            "effective_hash": self.effective_hash,
            "semantic_hash": self.semantic_hash,
            "restart_required": list(self.restart_required),
            "applied": dict(self.applied),
        }


class RuntimeConfigReloader:
    """Validate and swap lightweight runtime configuration atomically."""

    def __init__(
        self,
        config: EffectiveConfig,
        *,
        config_path: str | Path | None = None,
        personas_dir: str | Path | None = None,
    ) -> None:
        self._config = config
        configured_path = config_path or getattr(
            config,
            "manifest_path",
            DEFAULT_MANIFEST_PATH,
        )
        self.config_path = Path(configured_path).resolve()
        self.personas_dir = personas_dir
        self.version = getattr(config, "version", 1)

    @property
    def config(self) -> EffectiveConfig:
        return self._config

    def reload(self) -> ReloadResult:
        """Reload config from disk, preserving the previous config on failure."""
        schema_restart = _schema_restart_required(self.config_path, self._config)
        if schema_restart:
            return self._preserved_result(
                error="Configuration change requires restart",
                restart_required=schema_restart,
            )

        try:
            requested_profile = os.getenv("ANIMETTA_PROFILE") or self._config.profile
            candidate = load_effective_config(
                self.config_path,
                profile=requested_profile,
                personas_dir=self.personas_dir,
            )
            refreshed, restart_required = classify_effective_config_diff(
                self._config,
                candidate,
            )
            if restart_required:
                return self._preserved_result(
                    error="Configuration change requires restart",
                    restart_required=restart_required,
                )

            next_config = candidate.model_copy(update={"version": self.version + 1})
            self.version = next_config.version
            self._config = next_config
            logger.info(
                "[RuntimeConfigReload] Reloaded config snapshot: persona={}, version={}",
                next_config.persona,
                self.version,
            )
            return ReloadResult(
                ok=True,
                version=self.version,
                persona=next_config.persona,
                refreshed=refreshed,
                effective_hash=next_config.effective_hash,
                semantic_hash=next_config.semantic_hash,
            )
        except Exception as exc:
            error = redact_runtime_diagnostic(str(exc)) or type(exc).__name__
            logger.warning("[RuntimeConfigReload] Reload failed: {}", error)
            return self._preserved_result(error=error)

    def _preserved_result(
        self,
        *,
        error: str,
        restart_required: list[str] | None = None,
    ) -> ReloadResult:
        return ReloadResult(
            ok=False,
            version=self.version,
            persona=self._config.persona,
            refreshed=[],
            error=error,
            preserved=True,
            effective_hash=getattr(self._config, "effective_hash", ""),
            semantic_hash=getattr(self._config, "semantic_hash", ""),
            restart_required=restart_required or [],
        )


def classify_effective_config_diff(
    current: EffectiveConfig,
    candidate: EffectiveConfig,
) -> tuple[list[str], list[str]]:
    """Classify candidate fields into hot-reload and restart-only changes."""
    refreshed: set[str] = set()
    restart_required: set[str] = set()

    if current.schema_version != candidate.schema_version:
        restart_required.add("schema_version")
    if current.profile != candidate.profile:
        restart_required.add("profile")
    if restart_required:
        return [], sorted(restart_required)

    for path in _diff_paths(current.services.model_dump(), candidate.services.model_dump()):
        restart_required.add(f"services.{path}")
    for path in _diff_paths(current.policy.model_dump(), candidate.policy.model_dump()):
        restart_required.add(f"policy.{path}")
    for path in _diff_paths(
        current.application.system.model_dump(),
        candidate.application.system.model_dump(),
    ):
        restart_required.add(f"application.system.{path}")

    if (
        current.application.persona != candidate.application.persona
        or current.persona_snapshot_json != candidate.persona_snapshot_json
    ):
        refreshed.add("persona")
    if current.application.humor != candidate.application.humor:
        refreshed.add("ui")
    for path in _diff_paths(
        current.application.observability,
        candidate.application.observability,
    ):
        restart_required.add(f"application.observability.{path}")

    for path in _diff_paths(current.runtime.model_dump(), candidate.runtime.model_dump()):
        if path in _HOT_RUNTIME_FIELDS:
            refreshed.add("ui")
        else:
            restart_required.add(f"runtime.{path}")

    for category in ("llm", "asr", "tts", "vad"):
        current_provider = current.providers[category]
        candidate_provider = candidate.providers[category]
        if current_provider.name != candidate_provider.name:
            continue
        for path in _diff_paths(
            current_provider.declaration_dict(),
            candidate_provider.declaration_dict(),
        ):
            if category == "llm" and path in _HOT_LLM_FIELDS:
                refreshed.add("llm")
            else:
                restart_required.add(f"providers.{category}.{path}")

    return sorted(refreshed), sorted(restart_required)


def _diff_paths(current: Any, candidate: Any, prefix: str = "") -> list[str]:
    if isinstance(current, dict) and isinstance(candidate, dict):
        paths: list[str] = []
        for key in sorted(set(current) | set(candidate)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in current or key not in candidate:
                paths.append(child)
            else:
                paths.extend(_diff_paths(current[key], candidate[key], child))
        return paths
    if current != candidate:
        return [prefix]
    return []


def _schema_restart_required(
    config_path: Path,
    current: EffectiveConfig,
) -> list[str]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if isinstance(raw, dict) and raw.get("schema_version") != current.schema_version:
        return ["schema_version"]
    return []


def redact_runtime_diagnostic(value: str | None) -> str | None:
    """Redact likely secret tokens from diagnostic text."""
    if value is None:
        return None
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", value)
    redacted = re.sub(
        r"(?i)((?:api[_-]?key|token|authorization)\s*[:=]\s*)[^\s,;]+",
        r"\1***",
        redacted,
    )
    redacted = re.sub(r"[A-Za-z]:\\[^\n\r]+", "<path>", redacted)
    redacted = re.sub(r"/(?:[^\s/:]+/)+[^\s:,]+", "<path>", redacted)
    return redacted


__all__ = [
    "ReloadResult",
    "RuntimeConfigReloader",
    "classify_effective_config_diff",
    "redact_runtime_diagnostic",
]
