"""Content-free runtime readiness snapshots for the Anima golden path.

The functions in this module only inspect already-cached lifecycle state.  They
must never load a model, contact a provider, or serialize prompts, credentials,
reference assets, or user content.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
_DEEPSEEK_MODEL = "deepseek-v4-flash"
_PRELOAD_STATES = {"pending", "loading", "ready", "failed", "closing", "closed"}
_CONNECTIVITY_STATES = {"pending", "loading", "ready", "failed"}
_SAFE_CONNECTIVITY_REASONS = {
    "endpoint_mismatch",
    "endpoint_missing",
    "endpoint_policy",
    "model_unavailable",
    "no_api_key",
    "probe_unavailable",
    "request_failed",
    "timeout",
    "unauthorized",
}
_SAFE_FRONTEND_REASONS = {
    "assets_missing",
    "assets_unavailable",
    "frontend_state_unavailable",
}
_SAFE_INIT_REASONS = {
    "initialization_cancelled",
    "initialization_failed",
}


@dataclass(frozen=True)
class RuntimeReadinessSnapshot:
    """A JSON-safe, content-free view of cached runtime readiness."""

    ready: bool
    profile: str
    acceptance_eligible: bool
    components: dict[str, dict[str, Any]]

    @property
    def status(self) -> str:
        return "ready" if self.ready else "not_ready"

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-serializable representation."""
        return {
            "schema_version": 1,
            "status": self.status,
            "ready": self.ready,
            "service": "anima",
            "profile": self.profile,
            "acceptance_eligible": self.acceptance_eligible,
            "components": {
                name: dict(component)
                for name, component in self.components.items()
            },
        }


def frontend_asset_readiness(frontend_dist: Path) -> dict[str, str | bool | None]:
    """Inspect frontend assets once at server construction time.

    Only a content-free status is returned; the filesystem path is deliberately
    omitted from the public snapshot.
    """
    try:
        ready = frontend_dist.is_dir() and (frontend_dist / "index.html").is_file()
    except OSError:
        return {
            "state": "failed",
            "ready": False,
            "reason": "assets_unavailable",
        }
    return {
        "state": "ready" if ready else "failed",
        "ready": ready,
        "reason": None if ready else "assets_missing",
    }


def build_runtime_readiness_snapshot(
    *,
    config: Any,
    llm_engine: Any,
    tts_engine: Any,
    model_manager: Any,
    init_state: str,
    init_reason: str | None,
    connectivity: Any,
    frontend: Any,
    development_ready: bool,
) -> RuntimeReadinessSnapshot:
    """Build a readiness snapshot without performing I/O."""
    profile = _runtime_profile(config)
    frontend_component = _frontend_component(frontend, required=profile == "golden")

    if profile != "golden":
        state = "ready" if development_ready else _safe_lifecycle_state(init_state)
        pool_component = {
            "state": state,
            "ready": bool(development_ready),
            "reason": None if development_ready else "initializing",
        }
        llm_component = _runtime_service_component(
            llm_engine,
            configured_provider=getattr(getattr(config, "services", None), "agent", None),
        )
        tts_component = _runtime_service_component(
            tts_engine,
            configured_provider=getattr(getattr(config, "services", None), "tts", None),
        )
        return RuntimeReadinessSnapshot(
            ready=bool(development_ready),
            profile=profile,
            acceptance_eligible=False,
            components={
                "pool": pool_component,
                "llm": llm_component,
                "tts": tts_component,
                "frontend": frontend_component,
            },
        )

    llm_component = _golden_llm_component(config, llm_engine, connectivity)
    tts_component = _golden_tts_component(config, tts_engine, model_manager)
    pool_ready = llm_component["ready"] and tts_component["ready"]
    if init_state == "failed":
        safe_init_reason = (
            init_reason
            if init_reason in _SAFE_INIT_REASONS
            else "initialization_failed"
        )
        pool_component = {
            "state": "failed",
            "ready": False,
            "reason": safe_init_reason,
        }
    elif init_state != "ready":
        pool_component = {
            "state": _safe_lifecycle_state(init_state),
            "ready": False,
            "reason": None,
        }
    else:
        pool_component = {
            "state": "ready" if pool_ready else "failed",
            "ready": bool(pool_ready),
            "reason": None if pool_ready else "component_not_ready",
        }

    ready = bool(pool_component["ready"] and frontend_component["ready"])
    return RuntimeReadinessSnapshot(
        ready=ready,
        profile="golden",
        acceptance_eligible=True,
        components={
            "pool": pool_component,
            "llm": llm_component,
            "tts": tts_component,
            "frontend": frontend_component,
        },
    )


def unwrap_tracing_proxy(engine: Any) -> Any:
    """Unwrap any number of tracing proxies, failing safely on cycles."""
    from animetta.observability.service_proxy import InstrumentedServiceProxy
    from animetta.tracing.proxy import TracingProxy

    current = engine
    seen: set[int] = set()
    while isinstance(current, (TracingProxy, InstrumentedServiceProxy)):
        identity = id(current)
        if identity in seen:
            return None
        seen.add(identity)
        try:
            current = current._target
        except Exception:
            return None
    return current


def _runtime_service_component(
    engine: Any,
    *,
    configured_provider: Any,
) -> dict[str, Any]:
    """Expose bounded provider identity for non-golden runtime health."""
    target = unwrap_tracing_proxy(engine)
    if target is None:
        return {
            "state": "failed",
            "ready": False,
            "provider": str(configured_provider) if configured_provider else None,
            "model": None,
            "reason": "engine_missing",
        }
    try:
        model = object.__getattribute__(engine, "_model")
    except (AttributeError, TypeError):
        model = getattr(target, "model", None)
    return {
        "state": "ready",
        "ready": True,
        "provider": str(configured_provider) if configured_provider else None,
        "model": str(model) if model is not None else None,
        "reason": None,
    }


def canonical_deepseek_endpoint(value: Any) -> str | None:
    """Return a canonical official DeepSeek HTTPS endpoint without I/O."""
    if value is None:
        return None
    try:
        raw = str(value).strip()
        if not raw:
            return None
        parsed = urlsplit(raw)
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != "api.deepseek.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 443}
        ):
            return None
        path = parsed.path.rstrip("/")
        if path not in {"", "/v1"}:
            return None
    except (TypeError, ValueError):
        return None
    return f"https://api.deepseek.com{path}"


def normalize_reference_path(value: Any) -> str | None:
    """Normalize an asset identity lexically without touching the filesystem."""
    if value is None:
        return None
    try:
        raw = str(value).strip()
    except Exception:
        return None
    if not raw:
        return None
    return os.path.normcase(os.path.normpath(raw)).replace("\\", "/")


def _runtime_profile(config: Any) -> str:
    try:
        value = getattr(getattr(config, "system", None), "runtime_profile", None)
    except Exception:
        value = None
    return value if value in {"development", "test", "golden"} else "development"


def _safe_lifecycle_state(value: Any) -> str:
    return value if value in {"pending", "loading", "ready", "failed", "closing", "closed"} else "failed"


def _frontend_component(frontend: Any, *, required: bool) -> dict[str, Any]:
    try:
        state = frontend.get("state")
        ready = frontend.get("ready") is True
        reason = frontend.get("reason")
    except Exception:
        state = "failed"
        ready = False
        reason = "frontend_state_unavailable"

    if state not in {"ready", "failed"} or (state == "ready") is not ready:
        state = "failed"
        ready = False
        reason = "frontend_state_unavailable"
    if reason not in _SAFE_FRONTEND_REASONS:
        reason = None if ready else "frontend_state_unavailable"

    return {
        "state": state,
        "ready": ready if required else True,
        "required": required,
        "reason": reason,
    }


def _golden_llm_component(
    config: Any,
    engine: Any,
    connectivity: Any,
) -> dict[str, Any]:
    base = {
        "state": "failed",
        "ready": False,
        "provider": "deepseek",
        "model": _DEEPSEEK_MODEL,
        "reason": "engine_missing",
        "thinking": "disabled",
    }
    target = unwrap_tracing_proxy(engine)

    from animetta.services.llm.mock_llm import MockLLM
    from animetta.services.llm.openai_llm import OpenAILLM

    if isinstance(target, MockLLM):
        return {**base, "reason": "unexpected_mock"}
    if not isinstance(target, OpenAILLM):
        return {**base, "reason": "unexpected_provider"}

    try:
        selected = config.services.agent
        configured = config.agent.llm_config
        provider_ok = selected == "deepseek" and configured.type == "deepseek"
        model_ok = configured.model == _DEEPSEEK_MODEL and target.model == _DEEPSEEK_MODEL
        thinking_ok = (
            configured.thinking == "disabled"
            and target.extra_body.get("thinking", {}).get("type") == "disabled"
        )
    except Exception:
        return {**base, "reason": "configuration_unavailable"}

    if not provider_ok:
        return {**base, "reason": "unexpected_provider"}
    try:
        if target.provider_identity != "deepseek":
            return {**base, "reason": "provider_identity"}
    except Exception:
        return {**base, "reason": "provider_identity"}

    configured_raw_endpoint = getattr(configured, "base_url", None)
    engine_raw_endpoint = getattr(target, "base_url", None)
    if not configured_raw_endpoint or not engine_raw_endpoint:
        return {**base, "reason": "endpoint_missing"}
    configured_endpoint = canonical_deepseek_endpoint(configured_raw_endpoint)
    engine_endpoint = canonical_deepseek_endpoint(engine_raw_endpoint)
    if configured_endpoint is None or engine_endpoint is None:
        return {**base, "reason": "endpoint_policy"}
    if configured_endpoint != engine_endpoint:
        return {**base, "reason": "endpoint_mismatch"}
    if not model_ok:
        return {**base, "reason": "unexpected_model"}
    if not thinking_ok:
        return {**base, "reason": "thinking_policy"}

    try:
        state = connectivity.get("state")
        ready = connectivity.get("ready") is True
        reason = connectivity.get("reason")
    except Exception:
        return {**base, "reason": "connectivity_status_unavailable"}
    if state not in _CONNECTIVITY_STATES or ready is not (state == "ready"):
        return {**base, "reason": "connectivity_status_unavailable"}
    if ready:
        return {**base, "state": "ready", "ready": True, "reason": None}
    if reason not in _SAFE_CONNECTIVITY_REASONS:
        reason = None if state in {"pending", "loading"} else "request_failed"
    return {**base, "state": state, "reason": reason}


def _golden_tts_component(
    config: Any,
    engine: Any,
    model_manager: Any,
) -> dict[str, Any]:
    base = {
        "state": "failed",
        "ready": False,
        "provider": "qwen3",
        "model": _QWEN_MODEL,
        "reason": "engine_missing",
        "voice": "alice_vc",
        "clone_prompt_ready": False,
    }
    target = unwrap_tracing_proxy(engine)

    from animetta.services.tts.mock_tts import MockTTS
    from animetta.services.tts.qwen3_tts import Qwen3TTSTTS

    if isinstance(target, MockTTS):
        return {**base, "reason": "unexpected_mock"}
    if not isinstance(target, Qwen3TTSTTS):
        return {**base, "reason": "unexpected_provider"}

    try:
        configured = config.tts
        configured_path = normalize_reference_path(configured.ref_audio_path)
        engine_path = normalize_reference_path(target.ref_audio_path)
        config_ok = (
            config.services.tts == "alice_vc"
            and configured.type == "qwen3"
            and configured.model == _QWEN_MODEL
            and configured.x_vector_only is False
            and bool(configured.ref_audio_path)
            and bool(configured.ref_text)
        )
        engine_ok = (
            target.model == _QWEN_MODEL
            and target.x_vector_only is False
            and bool(target.ref_audio_path)
            and bool(target.ref_text)
        )
    except Exception:
        return {**base, "reason": "configuration_unavailable"}
    if not config_ok or not engine_ok:
        return {**base, "reason": "alice_icl_contract"}
    if (
        configured_path != engine_path
        or configured.ref_text != target.ref_text
    ):
        return {**base, "reason": "alice_asset_mismatch"}

    manager_state = _model_state(model_manager, "tts")
    if manager_state == "unavailable":
        return {**base, "reason": "preload_untracked"}
    if manager_state == "error":
        return {**base, "reason": "preload_failed"}
    if manager_state in {"unloaded", "loading"}:
        state = "pending" if manager_state == "unloaded" else "loading"
        return {**base, "state": state, "reason": None}
    if manager_state != "loaded":
        return {**base, "reason": "preload_status_unavailable"}

    try:
        status = target.preload_status
        if not isinstance(status, dict):
            raise TypeError("invalid preload status")
        preload_state = status.get("state")
        ready = status.get("ready") is True
    except Exception:
        return {**base, "reason": "preload_status_unavailable"}

    if preload_state not in _PRELOAD_STATES or ready is not (preload_state == "ready"):
        return {**base, "reason": "preload_status_unavailable"}
    if ready:
        return {
            **base,
            "state": "ready",
            "ready": True,
            "reason": None,
            "clone_prompt_ready": True,
        }
    reason = "preload_failed" if preload_state == "failed" else None
    return {**base, "state": preload_state, "reason": reason}


def _model_state(model_manager: Any, name: str) -> str:
    try:
        statuses = model_manager.get_status()
        state = statuses.get(name)
    except Exception:
        return "unavailable"
    return state if isinstance(state, str) else "unavailable"
