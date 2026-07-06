from __future__ import annotations

from scripts.route_smoke import run_smoke_probes


def test_route_smoke_probes_lightweight_routes() -> None:
    results = run_smoke_probes()

    assert results
    assert all(result.ok for result in results)


def test_route_smoke_covers_metrics_endpoint() -> None:
    results = run_smoke_probes()

    assert any(result.path == "/metrics" for result in results)


def test_route_smoke_covers_stats_api_routes() -> None:
    results = run_smoke_probes()
    paths = {result.path for result in results}

    assert {
        "/api/stats/overview",
        "/api/stats/nodes",
        "/api/stats/traces",
        "/api/stats/traces/__missing__",
        "/api/stats/traces/__missing__/tree",
    }.issubset(paths)


def test_route_smoke_covers_config_reload_route() -> None:
    results = run_smoke_probes()

    assert any(
        result.method == "POST"
        and result.path == "/api/config/reload"
        and result.expected_status == 400
        for result in results
    )
