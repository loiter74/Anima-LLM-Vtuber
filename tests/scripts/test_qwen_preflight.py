from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import qwen_preflight as preflight

ROOT = Path(__file__).resolve().parents[2]


def test_qwen_preflight_entrypoint_exists() -> None:
    assert (ROOT / "scripts" / "qwen_preflight.py").is_file()


EXPECTED_IDENTITY = {
    "service": "qwen-tts",
    "api_version": "v1",
    "provider": "qwen3",
    "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "revision": "5d83992436eae1d760afd27aff78a71d676296fc",
    "voice": "alice",
}


def test_exact_ready_identity_is_accepted() -> None:
    payload = {"ready": True, **EXPECTED_IDENTITY, "sample_rate": 24000}

    assert preflight.validate_ready_identity(payload, EXPECTED_IDENTITY) == payload


@pytest.mark.parametrize("field", ["provider", "model", "revision", "voice"])
def test_stale_ready_identity_fails_with_explicit_deploy_remediation(field: str) -> None:
    payload = {"ready": True, **EXPECTED_IDENTITY}
    payload[field] = "stale"

    with pytest.raises(preflight.QwenPreflightError) as exc_info:
        preflight.validate_ready_identity(payload, EXPECTED_IDENTITY)

    assert exc_info.value.category == "identity_mismatch"
    assert "qwen-deploy" in str(exc_info.value)


def test_preflight_reads_health_then_authenticated_ready_without_mutation() -> None:
    calls: list[tuple[str, str | None]] = []

    def request_json(url: str, authorization: str | None) -> dict:
        calls.append((url, authorization))
        if url.endswith("/health"):
            return {"status": "ok", "service": "qwen-tts", "api_version": "v1"}
        return {"ready": True, **EXPECTED_IDENTITY}

    evidence = preflight.run_preflight(
        base_url="http://127.0.0.1:8766",
        api_key="secret",
        expected_identity=EXPECTED_IDENTITY,
        request_json=request_json,
        attempts=1,
        interval_seconds=0,
    )

    assert evidence["status"] == "passed"
    assert evidence["identity"] == {"ready": True, **EXPECTED_IDENTITY}
    assert calls == [
        ("http://127.0.0.1:8766/health", None),
        ("http://127.0.0.1:8766/ready", "Bearer secret"),
    ]


def test_unavailable_service_fails_with_start_remediation_after_bounded_retries() -> None:
    calls = 0

    def request_json(_url: str, _authorization: str | None) -> dict:
        nonlocal calls
        calls += 1
        raise OSError("connection refused")

    with pytest.raises(preflight.QwenPreflightError) as exc_info:
        preflight.run_preflight(
            base_url="http://127.0.0.1:8766",
            api_key="secret",
            expected_identity=EXPECTED_IDENTITY,
            request_json=request_json,
            attempts=3,
            interval_seconds=0,
        )

    assert calls == 3
    assert exc_info.value.category == "unavailable"
    assert "qwen-up" in str(exc_info.value)


def test_missing_api_key_fails_before_any_request() -> None:
    called = False

    def request_json(_url: str, _authorization: str | None) -> dict:
        nonlocal called
        called = True
        return {}

    with pytest.raises(preflight.QwenPreflightError) as exc_info:
        preflight.run_preflight(
            base_url="http://127.0.0.1:8766",
            api_key="",
            expected_identity=EXPECTED_IDENTITY,
            request_json=request_json,
        )

    assert called is False
    assert exc_info.value.category == "configuration"
    assert "QWEN_TTS_API_KEY" in str(exc_info.value)


def test_expected_settings_resolve_when_host_worker_url_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWEN_TTS_API_KEY", "secret")
    monkeypatch.delenv("QWEN_TTS_URL", raising=False)

    api_key, identity = preflight.load_expected_settings(
        fallback_base_url="http://127.0.0.1:8766",
    )

    assert api_key == "secret"
    assert identity == EXPECTED_IDENTITY
    assert "QWEN_TTS_URL" not in os.environ


HOST_TTS_IDENTITY = {
    "service": "qwen-tts",
    "api_version": "v1",
    "provider": "qwen3-tts-gguf-host",
    "model": "Qwen3-TTS-1.7B-Base",
    "revision": "0eb32e283ee46b86820c67843abb04cf12bc58d7",
    "voice": "tosaka-rin-cn",
}


def test_host_tts_mode_returns_local_gguf_identity_without_manifest_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-tts mode resolves the local gguf identity from QWEN_TTS_API_KEY alone.

    The local gguf-host runtime (port 8767) does not declare a production remote
    worker in the manifest, so preflight must resolve its identity directly from
    the runtime lifecycle HOST_TTS_IDENTITY, not from load_remote_tts_worker_config.
    """
    monkeypatch.setenv("QWEN_TTS_API_KEY", "host-secret")

    api_key, identity = preflight.load_expected_settings(mode="host-tts")

    assert api_key == "host-secret"
    assert identity == HOST_TTS_IDENTITY


def test_host_tts_mode_runs_against_8767_and_accepts_local_identity() -> None:
    """run_preflight in host-tts mode probes /ready with QWEN_TTS_API_KEY auth."""

    calls: list[tuple[str, str | None]] = []

    def request_json(url: str, authorization: str | None) -> dict:
        calls.append((url, authorization))
        if url.endswith("/health"):
            return {"status": "ok", "service": "qwen-tts", "api_version": "v1"}
        return {"ready": True, **HOST_TTS_IDENTITY, "sample_rate": 24000}

    evidence = preflight.run_preflight(
        base_url="http://127.0.0.1:8767",
        api_key="host-secret",
        expected_identity=HOST_TTS_IDENTITY,
        request_json=request_json,
        attempts=1,
        interval_seconds=0,
    )

    assert evidence["status"] == "passed"
    assert calls == [
        ("http://127.0.0.1:8767/health", None),
        ("http://127.0.0.1:8767/ready", "Bearer host-secret"),
    ]
