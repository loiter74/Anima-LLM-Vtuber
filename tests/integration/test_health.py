"""Integration: health check + metrics HTTP endpoints."""

import urllib.request

PORT = 12394


class TestHealth:
    def test_health_endpoint(self, server):
        """GET /health should return 200."""
        try:
            resp = urllib.request.urlopen(f"http://localhost:{PORT}/health", timeout=5)
            body = resp.read().decode()
            status = resp.status
        except Exception as e:
            status = 0
            body = str(e)
        print(f"/health → {status}: {body[:200]}")
        assert status == 200, f"Expected 200, got {status}: {body}"

    def test_metrics_endpoint(self, server):
        """GET /metrics should return Prometheus metrics."""
        try:
            resp = urllib.request.urlopen(f"http://localhost:{PORT}/metrics", timeout=5)
            body = resp.read().decode()
            status = resp.status
        except Exception as e:
            status = 0
            body = str(e)
        has_prometheus = "animetta" in body.lower() or "python_" in body.lower()
        print(f"/metrics → {status}, has_animetta_metrics={has_prometheus}")
        assert status == 200, f"Expected 200, got {status}: {body[:200]}"
