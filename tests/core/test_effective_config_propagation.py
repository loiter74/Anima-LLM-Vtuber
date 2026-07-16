from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from animetta.config.manifest import EffectiveConfig, load_effective_config
from animetta.core.service_pool import ServicePool
from animetta.orchestration.server import stats_api
from animetta.orchestration.server.session import SessionManager
from animetta.orchestration.server.websocket import create_server

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def effective_config(monkeypatch: pytest.MonkeyPatch) -> EffectiveConfig:
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
    return load_effective_config(
        PROJECT_ROOT / "config" / "animetta.yaml",
        profile="test",
    )


def test_run_002_server_holders_share_one_effective_config_object(
    effective_config: EffectiveConfig,
) -> None:
    server = create_server(effective_config)

    assert server.config is effective_config
    assert server.runtime_reloader is not None
    assert server.runtime_reloader.config is effective_config
    assert server.route_handlers is not None
    assert server.route_handlers.global_config is effective_config
    assert ServicePool._runtime_config is effective_config
    assert stats_api._runtime_config is effective_config
    assert server.inspection_runtime().readiness_snapshot().profile == "test"


@pytest.mark.asyncio
async def test_run_003_new_session_inherits_config_version_and_hash(
    effective_config: EffectiveConfig,
) -> None:
    manager = SessionManager()
    pooled = {
        "llm_engine": object(),
        "tts_engine": object(),
        "asr_engine": object(),
    }

    with (
        patch.object(ServicePool, "get_context", return_value=pooled),
        patch(
            "animetta.core.service_context.ServiceContext.init_vad",
            new=AsyncMock(),
        ),
        patch(
            "animetta.core.service_context.ServiceContext.init_memory",
            new=AsyncMock(),
        ),
        patch(
            "animetta.core.service_context.ServiceContext.init_emotion_analyzer",
            new=AsyncMock(),
        ),
    ):
        context = await manager.get_or_create_context(
            "session-1",
            effective_config,
            AsyncMock(),
        )

    assert context.config is effective_config
    assert context.runtime_config_version == effective_config.version
    assert context.runtime_config_hash == effective_config.effective_hash
