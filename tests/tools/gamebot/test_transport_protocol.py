"""Tests for the gamebot transport protocol abstraction."""

from __future__ import annotations

from typing import Any

import pytest

from animetta.tools.gamebot.transport import GameBotTransport


class FakeTransport:
    """Minimal fake implementing GameBotTransport for testing the protocol surface."""

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
        return {"status": "success", "result": "fake"}

    def on_event(self, callback: Any) -> None:
        self._event_callbacks.append(callback)

    @property
    def is_running(self) -> bool:
        return self.started and not self.stopped


def test_fake_transport_implements_protocol() -> None:
    """FakeTransport must satisfy the GameBotTransport protocol."""
    fake = FakeTransport()
    assert isinstance(fake, GameBotTransport)


def test_transport_protocol_requires_start() -> None:
    """GameBotTransport must declare start method."""
    assert hasattr(GameBotTransport, "start")


def test_transport_protocol_requires_stop() -> None:
    assert hasattr(GameBotTransport, "stop")


def test_transport_protocol_requires_send_command() -> None:
    assert hasattr(GameBotTransport, "send_command")


def test_transport_protocol_requires_on_event() -> None:
    assert hasattr(GameBotTransport, "on_event")


def test_transport_protocol_requires_is_running() -> None:
    assert hasattr(GameBotTransport, "is_running")


@pytest.mark.asyncio
async def test_fake_transport_start_stop() -> None:
    fake = FakeTransport()
    assert not fake.is_running
    await fake.start()
    assert fake.is_running
    await fake.stop()
    assert not fake.is_running


@pytest.mark.asyncio
async def test_fake_transport_send_command() -> None:
    fake = FakeTransport()
    result = await fake.send_command("status", {}, timeout=5.0)
    assert result == {"status": "success", "result": "fake"}
    assert fake.commands == [("status", {}, 5.0)]


def test_fake_transport_on_event() -> None:
    fake = FakeTransport()
    called_with: list[Any] = []
    fake.on_event(lambda evt: called_with.append(evt))
    assert len(fake._event_callbacks) == 1
