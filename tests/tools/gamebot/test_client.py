"""Tests for GameBotClient — the high-level client wrapping a transport."""

from __future__ import annotations

from typing import Any

import pytest

from animetta.tools.gamebot.client import GameBotClient


class FakeTransport:
    """Minimal fake transport for client testing."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.commands: list[tuple[str, dict[str, Any], float]] = []
        self.responses: dict[str, dict[str, Any]] = {}
        self._event_callbacks: list[Any] = []

    async def start(self, login_timeout: float = 15.0) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_command(
        self, action: str, params: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any]:
        self.commands.append((action, params, timeout))
        return self.responses.get(action, {"status": "success", "result": f"fake_{action}"})

    def on_event(self, callback: Any) -> None:
        self._event_callbacks.append(callback)

    @property
    def is_running(self) -> bool:
        return self.started and not self.stopped


@pytest.fixture
def fake_transport():
    return FakeTransport()


@pytest.fixture
def client(fake_transport):
    return GameBotClient(transport=fake_transport)


@pytest.mark.asyncio
async def test_client_start_delegates(client, fake_transport) -> None:
    await client.start(login_timeout=10.0)
    assert fake_transport.started
    assert fake_transport.is_running


@pytest.mark.asyncio
async def test_client_stop_delegates(client, fake_transport) -> None:
    await client.start()
    await client.stop()
    assert fake_transport.stopped


@pytest.mark.asyncio
async def test_client_send_command(client, fake_transport) -> None:
    result = await client.send_command("goto", {"x": 100, "y": 64, "z": -200}, timeout=30.0)
    assert result["status"] == "success"
    assert result["result"] == "fake_goto"
    assert fake_transport.commands == [("goto", {"x": 100, "y": 64, "z": -200}, 30.0)]


@pytest.mark.asyncio
async def test_client_get_status(client, fake_transport) -> None:
    result = await client.get_status()
    assert result["status"] == "success"
    assert fake_transport.commands[-1][0] == "status"


@pytest.mark.asyncio
async def test_client_event_subscription(client, fake_transport) -> None:
    received: list[dict] = []
    client.on_event(lambda evt: received.append(evt))
    # Callback should be registered on the transport
    assert len(fake_transport._event_callbacks) == 1


@pytest.mark.asyncio
async def test_client_is_running_reflects_transport(client, fake_transport) -> None:
    assert not client.is_running
    await client.start()
    assert client.is_running
    await client.stop()
    assert not client.is_running


async def test_client_implements_transport_independent_runtime_protocol(client) -> None:
    from animetta.tools.gamebot.runtime import GameBotRuntime

    assert isinstance(client, GameBotRuntime)


async def test_client_get_capabilities_returns_typed_manifest(client, fake_transport) -> None:
    fake_transport.responses["capabilities"] = {
        "status": "success",
        "result": {
            "protocol_version": "1.0",
            "runtime_id": "runtime-1",
            "capabilities": [
                {"name": "collect", "risk": "survival_safe", "parameters": {}},
            ],
        },
    }

    manifest = await client.get_capabilities()

    assert manifest.runtime_id == "runtime-1"
    assert manifest.capability("collect").risk.value == "survival_safe"
    assert fake_transport.commands[-1] == ("capabilities", {}, 5.0)


async def test_client_observe_propagates_correlation_and_returns_typed_snapshot(
    client, fake_transport
) -> None:
    fake_transport.responses["observe"] = {
        "status": "success",
        "result": {
            "observation_id": "obs-1",
            "correlation_id": "corr-observe",
            "runtime_id": "runtime-1",
            "captured_at": "2026-07-12T00:00:00Z",
            "inventory": {"oak_log": 1},
        },
    }

    observation = await client.observe("corr-observe")

    assert observation.inventory == {"oak_log": 1}
    assert fake_transport.commands[-1] == (
        "observe",
        {"correlation_id": "corr-observe"},
        5.0,
    )


async def test_client_execute_action_returns_typed_receipt(client, fake_transport) -> None:
    fake_transport.responses["execute_action"] = {
        "status": "success",
        "result": {
            "receipt_id": "receipt-1",
            "session_id": "session-1",
            "task_id": "task-1",
            "correlation_id": "corr-action",
            "runtime_id": "runtime-1",
            "capability": "collect",
            "params": {"block_type": "oak_log", "count": 1},
            "started_at": "2026-07-12T00:00:00Z",
            "finished_at": "2026-07-12T00:00:01Z",
            "before_observation_hash": "obs-0",
            "after_observation_hash": "obs-1",
            "outcome": "success",
        },
    }

    receipt = await client.execute_action(
        "collect",
        {"block_type": "oak_log", "count": 1},
        session_id="session-1",
        task_id="task-1",
        correlation_id="corr-action",
        timeout=30.0,
    )

    assert receipt.capability == "collect"
    action, params, timeout = fake_transport.commands[-1]
    assert action == "execute_action"
    assert params["session_id"] == "session-1"
    assert params["task_id"] == "task-1"
    assert params["correlation_id"] == "corr-action"
    assert params["capability"] == "collect"
    assert timeout == 30.0


async def test_client_eval_skill_cancel_and_health_are_runtime_operations(
    client, fake_transport
) -> None:
    fake_transport.responses["eval_skill"] = {
        "status": "success",
        "result": {
            "receipts": [
                {
                    "receipt_id": "receipt-skill",
                    "session_id": "session-1",
                    "task_id": "task-1",
                    "correlation_id": "corr-skill",
                    "runtime_id": "runtime-1",
                    "capability": "collect",
                    "params": {},
                    "started_at": "2026-07-12T00:00:00Z",
                    "finished_at": "2026-07-12T00:00:01Z",
                    "before_observation_hash": "obs-0",
                    "after_observation_hash": "obs-1",
                    "outcome": "success",
                }
            ],
            "output": {"collected": 1},
        },
    }
    fake_transport.responses["cancel_action"] = {
        "status": "success",
        "result": {"cancelled": True},
    }
    fake_transport.responses["health"] = {
        "status": "success",
        "result": {"healthy": True, "runtime_id": "runtime-1"},
    }

    execution = await client.eval_skill(
        "await collect('oak_log', 1)",
        allowed_capabilities=["collect"],
        session_id="session-1",
        task_id="task-1",
        correlation_id="corr-skill",
        timeout=30.0,
    )
    cancelled = await client.cancel_action("corr-skill")
    health = await client.health()

    assert execution.receipts[0].receipt_id == "receipt-skill"
    assert execution.output == {"collected": 1}
    assert cancelled == {"cancelled": True}
    assert health == {"healthy": True, "runtime_id": "runtime-1"}
