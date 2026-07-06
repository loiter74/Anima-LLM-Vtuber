from __future__ import annotations

from scripts.route_smoke import run_smoke_probes


def test_route_smoke_probes_lightweight_routes() -> None:
    results = run_smoke_probes()

    assert results
    assert all(result.ok for result in results)


def test_route_smoke_covers_metrics_endpoint() -> None:
    results = run_smoke_probes()

    assert any(result.path == "/metrics" for result in results)
