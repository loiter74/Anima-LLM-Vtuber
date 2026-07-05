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
        self._event_callbacks: list[Any] = []

    async def start(self, login_timeout: float = 15.0) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_command(self, action: str, params: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        self.commands.append((action, params, timeout))
        return {"status": "success", "result": f"fake_{action}"}

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
