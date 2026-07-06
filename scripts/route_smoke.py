#!/usr/bin/env python3
from __future__ import annotations

"""Lightweight ASGI route probes that avoid model prewarm."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from animetta.orchestration.server.websocket import WebSocketServer


@dataclass(frozen=True)
class ProbeResult:
    method: str
    path: str
    status_code: int
    ok: bool
    expected_status: int


def _make_lightweight_server() -> WebSocketServer:
    with (
        patch("animetta.orchestration.server.websocket.ModelLoadingManager") as mock_mlm,
        patch("animetta.orchestration.server.websocket.SessionManager") as mock_sessions,
        patch("animetta.orchestration.server.websocket.DesktopClientManager") as mock_desktop,
        patch("animetta.orchestration.server.websocket.Live2DManager") as mock_live2d,
        patch("animetta.orchestration.server.websocket.LifecycleManager") as mock_lifecycle,
    ):
        mock_model_manager = MagicMock()
        mock_model_manager.get_status.return_value = {}
        mock_mlm.return_value = mock_model_manager
        mock_sessions.return_value = MagicMock()
        mock_desktop.return_value = MagicMock()
        mock_live2d.return_value = MagicMock()
        mock_lifecycle.return_value = MagicMock()
        return WebSocketServer(config=None)


def run_smoke_probes() -> list[ProbeResult]:
    server = _make_lightweight_server()
    probes = [
        ("GET", "/metrics", 200),
        ("GET", "/api/stats/overview", 200),
        ("GET", "/api/stats/nodes", 200),
        ("GET", "/api/stats/traces", 200),
        ("GET", "/api/stats/traces/__missing__", 404),
        ("GET", "/api/stats/traces/__missing__/tree", 404),
        ("GET", "/api/singing/recent", 200),
        ("GET", "/api/singing/audio/__missing__.wav", 404),
        ("GET", "/api/singing/subtitle/__missing__.ass", 404),
        ("POST", "/api/config/reload", 400),
    ]
    results: list[ProbeResult] = []

    with TestClient(server.get_app()) as client:
        for method, path, expected_status in probes:
            response = client.request(method, path)
            results.append(
                ProbeResult(
                    method=method,
                    path=path,
                    status_code=response.status_code,
                    expected_status=expected_status,
                    ok=response.status_code == expected_status,
                )
            )

    return results


def main() -> int:
    results = run_smoke_probes()
    failures = [result for result in results if not result.ok]

    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(
            f"[{status}] {result.method} {result.path} -> {result.status_code} "
            f"(expected {result.expected_status})"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
