from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from animetta.config.runtime_reload import ReloadResult
from animetta.orchestration.server.websocket import WebSocketServer


def test_reload_config_endpoint_returns_structured_success():
    server = WebSocketServer(config=MagicMock())
    server.runtime_reloader = MagicMock()
    server.runtime_reloader.reload.return_value = ReloadResult(
        ok=True,
        version=3,
        persona="anima.v0.1",
        refreshed=["persona", "llm"],
    )

    client = TestClient(server.get_app())
    response = client.post("/api/config/reload")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "version": 3,
        "persona": "anima.v0.1",
        "refreshed": ["persona", "llm"],
        "error": None,
    }


def test_reload_config_endpoint_applies_reloaded_config_to_contexts():
    llm_config = SimpleNamespace(model="updated-model")
    new_config = SimpleNamespace(agent=SimpleNamespace(llm_config=llm_config))
    server = WebSocketServer(config=SimpleNamespace(agent=None))
    server.runtime_reloader = MagicMock()
    server.runtime_reloader.config = new_config
    server.runtime_reloader.reload.return_value = ReloadResult(
        ok=True,
        version=5,
        persona="anima.v0.1",
        refreshed=["persona", "llm"],
    )
    ctx = SimpleNamespace(
        config=server.config,
        runtime_config_version=1,
        llm_engine=SimpleNamespace(model="old-model"),
    )
    server.session_manager.contexts["sid"] = ctx

    client = TestClient(server.get_app())
    response = client.post("/api/config/reload")

    assert response.status_code == 200
    assert server.config is new_config
    assert ctx.config is new_config
    assert ctx.runtime_config_version == 5
    assert ctx.llm_engine.model == "updated-model"


def test_reload_config_endpoint_returns_400_on_validation_failure():
    server = WebSocketServer(config=MagicMock())
    server.runtime_reloader = MagicMock()
    server.runtime_reloader.reload.return_value = ReloadResult(
        ok=False,
        version=1,
        persona="anima.v0.1",
        error="invalid persona",
    )

    client = TestClient(server.get_app())
    response = client.post("/api/config/reload")

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert response.json()["persona"] == "anima.v0.1"
    assert response.json()["error"] == "invalid persona"


@pytest.mark.asyncio
async def test_apply_reloaded_config_updates_existing_contexts():
    server = WebSocketServer(config=MagicMock())
    new_config = MagicMock()
    ctx = MagicMock()
    ctx.config = MagicMock()
    ctx.llm_engine = MagicMock()
    server.session_manager.contexts["sid"] = ctx

    await server._apply_reloaded_config(new_config, version=4)

    assert server.config is new_config
    assert ctx.config is new_config
    assert ctx.runtime_config_version == 4
