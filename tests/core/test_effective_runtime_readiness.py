from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from animetta.config.manifest import EffectiveConfig, load_effective_config
from animetta.core.readiness import resolve_service_identity
from animetta.core.service_pool import ServicePool
from animetta.orchestration.server.stats_api import health_check
from animetta.services.tts.mock_tts import MockTTS


class _StaticModelManager:
    def __init__(self, **statuses: str) -> None:
        self.statuses = statuses

    def get_status(self) -> dict[str, str]:
        return dict(self.statuses)


class _StaticFailoverTTS:
    def __init__(
        self,
        *,
        primary_ready: bool = True,
        fallback_ready: bool = True,
    ) -> None:
        self.primary_ready = primary_ready
        self.fallback_ready = fallback_ready

    def readiness_snapshot(self) -> dict[str, object]:
        ready = self.primary_ready or self.fallback_ready
        return {
            "ready": ready,
            "degraded": ready and not (self.primary_ready and self.fallback_ready),
            "active_backend": (
                "primary" if self.primary_ready else "fallback" if self.fallback_ready else None
            ),
            "primary": {
                "ready": self.primary_ready,
                "error_category": None if self.primary_ready else "billing",
            },
            "fallback": {
                "ready": self.fallback_ready,
                "error_category": None if self.fallback_ready else "connection",
            },
            "circuit": {
                "state": "closed" if self.primary_ready else "open",
                "cooldown_remaining_seconds": 0.0 if self.primary_ready else 300.0,
            },
        }


@pytest.fixture
def effective_config(monkeypatch: pytest.MonkeyPatch) -> callable:
    for name in (
        "ANIMETTA_CONFIG",
        "ANIMETTA_LLM",
        "ANIMETTA_ASR",
        "ANIMETTA_TTS",
        "ANIMETTA_VAD",
        "ANIMETTA_LOCAL_LLM",
        "VITE_API_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANIMETTA_HOST", "127.0.0.1")
    monkeypatch.setenv("ANIMETTA_PORT", "12394")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "readiness-deepseek-secret")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "readiness-dashscope-secret")
    monkeypatch.setenv("MIMO_API_KEY", "readiness-mimo-secret")
    monkeypatch.setenv("QWEN_TTS_API_KEY", "readiness-qwen-secret")
    monkeypatch.setenv("QWEN_TTS_URL", "http://qwen-tts.internal:8001")
    monkeypatch.setenv("QWEN_HOST_TTS_URL", "http://host.docker.internal:8767")

    def _load(profile: str) -> EffectiveConfig:
        return load_effective_config("config/animetta.yaml", profile=profile)

    return _load


@pytest.fixture(autouse=True)
def reset_pool() -> None:
    previous = {
        name: getattr(ServicePool, name, None)
        for name in (
            "_runtime_config",
            "_model_manager",
            "_init_state",
            "_init_error",
            "_ready",
            "_llm",
            "_tts",
            "_asr",
            "_resolved_identities",
            "_llm_connectivity",
        )
    }
    ServicePool._runtime_config = None
    ServicePool._model_manager = None
    ServicePool._init_state = "pending"
    ServicePool._init_error = None
    ServicePool._ready = False
    ServicePool._llm = None
    ServicePool._tts = None
    ServicePool._asr = None
    ServicePool._resolved_identities = {}
    ServicePool._llm_connectivity = {
        "state": "pending",
        "ready": False,
        "reason": None,
    }
    yield
    for name, value in previous.items():
        setattr(ServicePool, name, value)


def _frontend(ready: bool = True) -> dict[str, str | bool | None]:
    return {
        "state": "ready" if ready else "failed",
        "ready": ready,
        "reason": None if ready else "assets_missing",
    }


def _resolved(config: EffectiveConfig) -> dict[str, dict[str, str | None]]:
    return {
        category: {
            "type": provider.type,
            "provider": provider.public_identity()["provider"],
            "model": provider.model,
            "voice": provider.voice,
        }
        for category, provider in config.providers.items()
    }


def _seed_ready(config: EffectiveConfig) -> None:
    ServicePool._runtime_config = config
    ServicePool._init_state = "ready"
    ServicePool._ready = True
    ServicePool._llm = object()
    ServicePool._tts = (
        _StaticFailoverTTS() if config.providers["tts"].type == "failover" else object()
    )
    ServicePool._asr = object()
    ServicePool._model_manager = _StaticModelManager(tts="loaded")
    ServicePool._resolved_identities = _resolved(config)
    ServicePool._llm_connectivity = {
        "state": "ready",
        "ready": True,
        "reason": None,
    }


def test_smoke_snapshot_publishes_one_config_identity_and_distinct_asr_tts_rows(
    effective_config,
) -> None:
    config = effective_config("smoke")
    _seed_ready(config)

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    assert payload["ready"] is True
    assert payload["profile"] == "smoke"
    assert payload["version"] == config.version
    assert payload["effective_hash"] == config.effective_hash
    assert payload["semantic_hash"] == config.semantic_hash
    assert payload["components"]["asr"]["configured"]["model"] == "mimo-v2.5-asr"
    assert payload["components"]["tts"]["configured"]["model"] == "mimo-v2.5-tts"
    assert payload["components"]["asr"] != payload["components"]["tts"]


def test_production_tts_exposes_exact_composite_and_child_status(
    effective_config,
) -> None:
    config = effective_config("production")
    _seed_ready(config)

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    tts = payload["components"]["tts"]
    assert tts["ready"] is True
    assert tts["configured"]["type"] == "failover"
    assert tts["configured"]["provider"] == "failover"
    assert tts["resolved"]["provider"] == "failover"
    assert tts["degraded"] is False
    assert tts["active_backend"] == "primary"
    assert tts["primary"] == {"ready": True, "error_category": None}
    assert tts["fallback"] == {"ready": True, "error_category": None}


@pytest.mark.parametrize(
    ("primary_ready", "fallback_ready", "expected_ready", "active_backend"),
    [
        (True, False, True, "primary"),
        (False, True, True, "fallback"),
        (False, False, False, None),
    ],
)
def test_production_composite_readiness_accepts_any_single_route(
    effective_config,
    primary_ready: bool,
    fallback_ready: bool,
    expected_ready: bool,
    active_backend: str | None,
) -> None:
    config = effective_config("production")
    _seed_ready(config)
    ServicePool._tts = _StaticFailoverTTS(
        primary_ready=primary_ready,
        fallback_ready=fallback_ready,
    )

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    tts = payload["components"]["tts"]
    assert tts["ready"] is expected_ready
    assert tts["degraded"] is expected_ready
    assert tts["active_backend"] == active_backend
    assert payload["ready"] is expected_ready


def test_selftest_requires_deepseek_connectivity(effective_config) -> None:
    config = effective_config("selftest")
    _seed_ready(config)
    ServicePool._llm_connectivity = {
        "state": "failed",
        "ready": False,
        "reason": "request_failed",
    }

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    assert payload["ready"] is False
    assert payload["components"]["llm"]["ready"] is False
    assert payload["components"]["llm"]["reason"] == "request_failed"


def test_selftest_requires_frontend_assets(effective_config) -> None:
    config = effective_config("selftest")
    _seed_ready(config)

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(False),
    ).to_dict()

    assert payload["ready"] is False
    assert payload["components"]["frontend"]["required"] is True
    assert payload["components"]["frontend"]["reason"] == "assets_missing"


def test_remote_identity_mismatch_fails_readiness_with_sanitized_cause(
    effective_config,
) -> None:
    config = effective_config("production")
    _seed_ready(config)
    ServicePool._resolved_identities["tts"]["voice"] = "wrong-voice"

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    assert payload["ready"] is False
    assert payload["components"]["tts"]["reason"] == "identity_mismatch"
    serialized = json.dumps(payload)
    assert "readiness-dashscope-secret" not in serialized
    assert "dashscope.aliyuncs.com" not in serialized


def test_production_dashscope_preload_failure_fails_pool_readiness(
    effective_config,
) -> None:
    config = effective_config("production")
    _seed_ready(config)
    ServicePool._model_manager = _StaticModelManager(tts="error")

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    assert payload["ready"] is False
    assert payload["components"]["tts"]["state"] == "failed"
    assert payload["components"]["tts"]["reason"] == "preload_failed"
    assert payload["components"]["pool"]["ready"] is False
    assert payload["components"]["pool"]["reason"] == "component_not_ready"
    serialized = json.dumps(payload)
    assert "readiness-dashscope-secret" not in serialized
    assert "dashscope.aliyuncs.com" not in serialized


def test_stale_config_snapshot_fails_closed(effective_config) -> None:
    active = effective_config("smoke")
    _seed_ready(active)
    stale_view = active.model_copy(update={"version": active.version + 1})

    payload = ServicePool.get_readiness_snapshot(
        config=stale_view,
        frontend=_frontend(),
    ).to_dict()

    assert payload["ready"] is False
    assert payload["components"]["pool"]["reason"] == "stale_config_snapshot"


def test_missing_service_pool_snapshot_fails_closed(effective_config) -> None:
    config = effective_config("smoke")

    payload = ServicePool.get_readiness_snapshot(
        config=config,
        frontend=_frontend(),
    ).to_dict()

    assert payload["ready"] is False
    assert payload["components"]["pool"]["reason"] == "pool_unavailable"


@pytest.mark.asyncio
async def test_health_is_cheap_and_never_reads_provider_readiness() -> None:
    with patch.object(
        ServicePool,
        "get_readiness_snapshot",
        side_effect=AssertionError("health must not read readiness"),
    ):
        response = await health_check(None)

    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "ok"


def test_ready_snapshot_uses_cached_remote_identity_without_network_call(
    effective_config,
) -> None:
    config = effective_config("production")
    _seed_ready(config)

    with patch(
        "animetta.services.tts.dashscope_tts._default_connector",
        side_effect=AssertionError("/ready must not perform network I/O"),
    ) as check:
        payload = ServicePool.get_readiness_snapshot(
            config=config,
            frontend=_frontend(),
        ).to_dict()

    assert payload["ready"] is True
    check.assert_not_called()


def test_resolver_reports_constructed_engine_type_instead_of_configured_type(
    effective_config,
) -> None:
    config = effective_config("production")
    configured = config.providers["tts"]

    identity = resolve_service_identity("tts", MockTTS(), configured)

    assert identity is not None
    assert identity["type"] == "mock"
    assert identity["type"] != configured.type
