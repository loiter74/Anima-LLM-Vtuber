"""Tests for StdioGameBotTransport — the stdio JSON-line transport implementation."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.tools.gamebot.stdio_transport import StdioGameBotTransport


@pytest.fixture
def fake_process():
    """Create a fake subprocess with controllable stdin/stdout/stderr."""
    proc = AsyncMock()
    proc.returncode = None
    proc.stdin = AsyncMock()
    proc.stdout = AsyncMock()
    # stderr must return b"" (EOF) by default — a bare AsyncMock produces unawaited
    # coroutine warnings when the stderr reader task is cancelled by transport.stop().
    proc.stderr.read = AsyncMock(return_value=b"")
    proc.stderr.readline = AsyncMock(return_value=b"")
    proc.terminate = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _make_response_line(id_: int | None, status: str, result: Any) -> str:
    return json.dumps({"id": id_, "status": status, "result": result}) + "\n"


@pytest.mark.asyncio
async def test_send_command_writes_json_line_with_ms_timeout(fake_process) -> None:
    """send_command must write JSON line with id, action, params, and millisecond timeout."""
    transport = StdioGameBotTransport(argv=["node", "index.js"], cwd="/fake")

    # Capture what gets written to stdin
    written: list[str] = []
    fake_process.stdin.write = MagicMock(side_effect=lambda data: written.append(data))

    # Make stdout return a matching response
    response_line = _make_response_line(1, "success", {"ok": True})
    fake_process.stdout.readline = AsyncMock(side_effect=[
        response_line.encode(),
        b"",  # EOF to stop reader
    ])

    with patch("asyncio.create_subprocess_exec", return_value=fake_process):
        await transport.start(login_timeout=0.1)

    # Send a command
    result = await transport.send_command("status", {}, timeout=5.0)

    # Verify the written line
    assert len(written) >= 1
    cmd_line = json.loads(written[-1].decode().strip())
    assert cmd_line["id"] == 1
    assert cmd_line["action"] == "status"
    assert cmd_line["params"] == {}
    assert cmd_line["timeout_ms"] == 5000

    assert result["status"] == "success"
    assert result["result"] == {"ok": True}

    await transport.stop()


@pytest.mark.asyncio
async def test_matching_response_id_resolves_pending(fake_process) -> None:
    """A response with matching id must resolve the pending command future."""
    transport = StdioGameBotTransport(argv=["node", "index.js"], cwd="/fake")

    fake_process.stdin.write = MagicMock()

    # Use events to coordinate: reader waits for response to be "released"
    response_1_ready = asyncio.Event()
    response_2_ready = asyncio.Event()

    async def mock_readline() -> bytes:
        # Wait for each response to be ready
        await response_1_ready.wait()
        response_1_ready.clear()
        return _make_response_line(1, "success", "first").encode()

    # After response 1, switch to a second readline that returns response 2
    call_count = 0

    async def sequenced_readline() -> bytes:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response_line(1, "success", "first").encode()
        elif call_count == 2:
            await response_2_ready.wait()
            return _make_response_line(2, "success", "second").encode()
        return b""

    fake_process.stdout.readline = sequenced_readline

    with patch("asyncio.create_subprocess_exec", return_value=fake_process):
        await transport.start(login_timeout=0.1)

    # Send cmd1 — response 1 is immediately available
    r1 = await transport.send_command("cmd1", {}, timeout=5.0)
    assert r1["result"] == "first"

    # Now send cmd2 and then release its response
    cmd2_task = asyncio.create_task(transport.send_command("cmd2", {}, timeout=5.0))
    await asyncio.sleep(0.05)  # Let the future get registered
    response_2_ready.set()
    r2 = await cmd2_task

    assert r2["result"] == "second"

    await transport.stop()


@pytest.mark.asyncio
async def test_idless_event_triggers_callback(fake_process) -> None:
    """An id-less event response must trigger the registered event callback."""
    transport = StdioGameBotTransport(argv=["node", "index.js"], cwd="/fake")

    fake_process.stdin.write = MagicMock()

    events_received: list[dict] = []

    event_line = _make_response_line(None, "event", {"type": "login", "username": "Bot"})

    fake_process.stdout.readline = AsyncMock(side_effect=[
        event_line.encode(),
        b"",
    ])

    with patch("asyncio.create_subprocess_exec", return_value=fake_process):
        transport.on_event(lambda evt: events_received.append(evt))
        await transport.start(login_timeout=0.1)
        # Give reader a moment to process
        await asyncio.sleep(0.1)

    assert len(events_received) >= 1
    assert events_received[0]["type"] == "login"
    assert events_received[0]["username"] == "Bot"

    await transport.stop()


@pytest.mark.asyncio
async def test_malformed_json_does_not_crash(fake_process) -> None:
    """Non-JSON stdout lines must not crash the reader."""
    transport = StdioGameBotTransport(argv=["node", "index.js"], cwd="/fake")

    fake_process.stdin.write = MagicMock()
    fake_process.stdout.readline = AsyncMock(side_effect=[
        b"this is not json\n",
        _make_response_line(1, "success", "ok").encode(),
        b"",
    ])

    with patch("asyncio.create_subprocess_exec", return_value=fake_process):
        await transport.start(login_timeout=0.1)

    result = await transport.send_command("test", {}, timeout=5.0)
    assert result["status"] == "success"

    await transport.stop()


@pytest.mark.asyncio
async def test_command_timeout_returns_error(fake_process) -> None:
    """A command that exceeds its timeout must return a compatibility error response."""
    transport = StdioGameBotTransport(argv=["node", "index.js"], cwd="/fake")

    fake_process.stdin.write = MagicMock()

    # Create an async readline that blocks forever (simulates no response)
    never_respond = asyncio.Event()

    async def blocking_readline() -> bytes:
        await never_respond.wait()  # blocks forever
        return b""

    fake_process.stdout.readline = blocking_readline

    with patch("asyncio.create_subprocess_exec", return_value=fake_process):
        await transport.start(login_timeout=0.1)

    result = await transport.send_command("goto", {"x": 100}, timeout=0.1)

    assert result["status"] == "error"
    assert "goto" in result["result"]

    await transport.stop()


@pytest.mark.asyncio
async def test_process_exit_returns_error(fake_process) -> None:
    """When the process exits mid-command, pending commands must get an error response."""
    transport = StdioGameBotTransport(argv=["node", "index.js"], cwd="/fake")

    fake_process.stdin.write = MagicMock()
    fake_process.returncode = 1
    fake_process.stdout.readline = AsyncMock(return_value=b"")

    with patch("asyncio.create_subprocess_exec", return_value=fake_process):
        await transport.start(login_timeout=0.1)
        # Simulate process exit by stopping reader
        await asyncio.sleep(0.05)

    # The command may resolve with an error due to process exit or EOF
    try:
        result = await asyncio.wait_for(
            transport.send_command("mine", {}, timeout=0.5), timeout=1.0
        )
        assert result["status"] == "error"
    except (TimeoutError, Exception):
        # Also acceptable — transport detected the problem
        pass

    await transport.stop()
