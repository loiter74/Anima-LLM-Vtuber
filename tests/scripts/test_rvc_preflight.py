from __future__ import annotations

import pytest

from scripts import rvc_preflight as preflight


def test_rvc_preflight_reads_health_then_authenticated_identity() -> None:
    calls: list[tuple[str, str | None]] = []

    def request_json(url: str, authorization: str | None) -> dict[str, object]:
        calls.append((url, authorization))
        if url.endswith("/health"):
            return {"status": "ok", "service": "rvc", "api_version": "v1"}
        return {"ready": True, **preflight.HOST_RVC_EXPECTED_IDENTITY}

    evidence = preflight.run_preflight(
        base_url="http://127.0.0.1:8769",
        api_key="secret",
        expected_identity=preflight.HOST_RVC_EXPECTED_IDENTITY,
        request_json=request_json,
    )

    assert evidence["status"] == "passed"
    assert calls == [
        ("http://127.0.0.1:8769/health", None),
        ("http://127.0.0.1:8769/ready", "Bearer secret"),
    ]


def test_rvc_preflight_rejects_stale_model_identity() -> None:
    payload = {"ready": True, **preflight.HOST_RVC_EXPECTED_IDENTITY, "revision": "stale"}

    with pytest.raises(preflight.RVCPreflightError) as exc_info:
        preflight.validate_ready_identity(payload, preflight.HOST_RVC_EXPECTED_IDENTITY)

    assert exc_info.value.category == "identity_mismatch"
    assert "host-rvc-stop" in str(exc_info.value)
