"""Tests for GameBotStateCollector."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from animetta.tools.gamebot.state_collector import GameBotStateCollector


class FakeClient:
    """Fake GameBotClient that returns controllable status responses."""

    def __init__(self) -> None:
        self._status_resp: dict[str, Any] = {"status": "success", "result": {}}
        self.start_called = False
        self.stop_called = False
        self._event_callbacks: list = []

    async def get_status(self) -> dict[str, Any]:
        return self._status_resp

    def set_status(self, resp: dict[str, Any]) -> None:
        self._status_resp = resp

    async def start(self) -> None:
        self.start_called = True

    async def stop(self) -> None:
        self.stop_called = True

    def on_event(self, callback: Any) -> None:
        self._event_callbacks.append(callback)


@pytest.mark.asyncio
async def test_collector_polls_status_and_emits() -> None:
    """Collector must poll get_status() and forward result to callback."""
    client = FakeClient()
    client.set_status({"status": "success", "result": {"health": 20, "food": 18}})

    emitted: list[dict] = []

    collector = GameBotStateCollector(client, interval=0.05, on_state=emitted.append)
    await collector.start()

    # Wait for at least one poll cycle
    await asyncio.sleep(0.15)
    await collector.stop()

    assert len(emitted) >= 1
    assert emitted[0]["health"] == 20
    assert emitted[0]["food"] == 18


@pytest.mark.asyncio
async def test_collector_ignores_error_responses() -> None:
    """Error status responses must not be forwarded to callback."""
    client = FakeClient()
    client.set_status({"status": "error", "result": "not connected"})

    emitted: list[dict] = []

    collector = GameBotStateCollector(client, interval=0.05, on_state=emitted.append)
    await collector.start()
    await asyncio.sleep(0.15)
    await collector.stop()

    assert len(emitted) == 0


@pytest.mark.asyncio
async def test_collector_error_does_not_stop_loop() -> None:
    """A failing callback must not stop the collector loop."""
    call_count = 0

    client = FakeClient()
    client.set_status({"status": "success", "result": {"tick": 1}})

    def failing_callback(data: dict) -> None:
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            raise RuntimeError("simulated callback error")

    collector = GameBotStateCollector(client, interval=0.05, on_state=failing_callback)
    await collector.start()
    await asyncio.sleep(0.2)
    await collector.stop()

    # Loop must survive the first callback error and call again
    assert call_count >= 2


@pytest.mark.asyncio
async def test_collector_stop_idempotent() -> None:
    """Calling stop twice must not raise."""
    client = FakeClient()
    collector = GameBotStateCollector(client, interval=0.05)

    await collector.start()
    await collector.stop()
    await collector.stop()  # must be safe
