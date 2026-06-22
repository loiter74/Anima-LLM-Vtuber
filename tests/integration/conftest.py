"""Conftest for integration tests."""

import os
import subprocess
import sys
import time
import urllib.request

import pytest
import socketio

PORT = 12394
URL = f"http://localhost:{PORT}"


def pytest_collection_modifyitems(config, items):
    """Auto-mark only tests located under tests/integration/ with the integration marker."""
    integration_marker = pytest.mark.integration
    for item in items:
        # Only mark items whose file path is under tests/integration/
        if "integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(integration_marker)


def _wait_for_http_health(process: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"server health endpoint did not become ready: {last_error}")


def _wait_for_socketio(timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        client = socketio.Client(reconnection=False)
        try:
            client.connect(URL, transports=["websocket"], wait_timeout=5)
            client.disconnect()
            return
        except Exception as exc:
            last_error = exc
        finally:
            if client.connected:
                client.disconnect()
        time.sleep(1)
    raise RuntimeError(f"socket.io websocket did not become ready: {last_error}")


@pytest.fixture(scope="session")
def server():
    """Start one shared Socket.IO server for integration tests."""
    process = subprocess.Popen(
        [sys.executable, "-m", "animetta.core.socketio_server"],
        env={**os.environ, "PYTHONPATH": "src", "ANIMETTA_PORT": str(PORT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    try:
        _wait_for_http_health(process)
        _wait_for_socketio()
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
