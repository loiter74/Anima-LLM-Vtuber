from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

LEGACY_SELECTORS = (
    "ANIMETTA_CONFIG",
    "ANIMETTA_LLM",
    "ANIMETTA_ASR",
    "ANIMETTA_TTS",
    "ANIMETTA_VAD",
    "ANIMETTA_LOCAL_LLM",
    "VITE_API_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "ASR_API_KEY",
    "TTS_API_KEY",
)


@pytest.fixture
def isolated_manifest_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Keep developer shell/.env values out of manifest regression tests."""
    for name in LEGACY_SELECTORS:
        monkeypatch.delenv(name, raising=False)
    for name in (
        "ANIMETTA_PROFILE",
        "ANIMETTA_HOST",
        "ANIMETTA_PORT",
        "ANIMETTA_BACKEND_URL",
        "QWEN_TTS_URL",
        "QWEN_TTS_API_KEY",
        "QWEN_HOST_TTS_URL",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MIMO_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def manifest_data() -> dict[str, Any]:
    """Small complete manifest used by loader tests."""
    return {
        "schema_version": 1,
        "application": {
            "persona": "anima.v0.1",
            "system": {"host": "${ANIMETTA_HOST}", "port": "${ANIMETTA_PORT}"},
        },
        "providers": {
            "llm": {
                "mock": {"type": "mock"},
                "deepseek": {
                    "type": "deepseek",
                    "api_key": "${DEEPSEEK_API_KEY}",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://api.deepseek.com/v1",
                },
            },
            "asr": {
                "mock": {"type": "mock"},
                "mimo-asr": {
                    "type": "mimo",
                    "api_key": "${MIMO_API_KEY}",
                    "model": "mimo-v2.5-asr",
                    "base_url": "https://api.xiaomimimo.com/v1",
                },
            },
            "tts": {
                "mock": {"type": "mock"},
                "mimo-tts": {
                    "type": "mimo",
                    "api_key": "${MIMO_API_KEY}",
                    "model": "mimo-v2.5-tts",
                    "base_url": "https://api.xiaomimimo.com/v1",
                    "voice": "mimo_default",
                },
                "qwen-alice": {
                    "type": "remote",
                    "api_key": "${QWEN_TTS_API_KEY}",
                    "base_url": "${QWEN_TTS_URL}",
                    "provider": "qwen3",
                    "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                    "voice": "alice",
                },
            },
            "vad": {
                "mock": {"type": "mock"},
                "mimo-vad": {
                    "type": "mimo",
                    "api_key": "${MIMO_API_KEY}",
                    "model": "mimo-v2.5-asr",
                    "base_url": "https://api.xiaomimimo.com/v1",
                },
            },
        },
        "profiles": {
            "test": {
                "services": {"llm": "mock", "asr": "mock", "tts": "mock", "vad": "mock"},
                "policy": {"allow_mock": True, "require_remote_identity": False},
                "runtime": {"debug": True},
            },
            "smoke": {
                "services": {
                    "llm": "deepseek",
                    "asr": "mimo-asr",
                    "tts": "mimo-tts",
                    "vad": "mimo-vad",
                },
                "policy": {"allow_mock": False, "require_remote_identity": True},
                "runtime": {"debug": False},
            },
            "selftest": {
                "services": {
                    "llm": "deepseek",
                    "asr": "mimo-asr",
                    "tts": "qwen-alice",
                    "vad": "mimo-vad",
                },
                "policy": {"allow_mock": False, "require_remote_identity": True},
                "runtime": {"debug": False, "tts_timeout_seconds": 120.0},
            },
            "production": {
                "services": {
                    "llm": "deepseek",
                    "asr": "mimo-asr",
                    "tts": "qwen-alice",
                    "vad": "mimo-vad",
                },
                "policy": {"allow_mock": False, "require_remote_identity": True},
                "runtime": {"debug": False},
            },
        },
    }


@pytest.fixture
def write_manifest(
    tmp_path: Path,
) -> Callable[[dict[str, Any]], Path]:
    def _write(data: dict[str, Any]) -> Path:
        path = tmp_path / "animetta.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def manifest_secrets(isolated_manifest_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    isolated_manifest_env.setenv("ANIMETTA_HOST", "127.0.0.1")
    isolated_manifest_env.setenv("ANIMETTA_PORT", "12394")
    isolated_manifest_env.setenv("DEEPSEEK_API_KEY", "test-deepseek-secret")
    isolated_manifest_env.setenv("MIMO_API_KEY", "test-mimo-secret")
    isolated_manifest_env.setenv("QWEN_TTS_API_KEY", "test-qwen-secret")
    isolated_manifest_env.setenv(
        "QWEN_HOST_TTS_URL",
        "http://host.docker.internal:8767",
    )
    isolated_manifest_env.setenv("QWEN_TTS_URL", "http://qwen-tts.test:8001")
    isolated_manifest_env.setenv("DASHSCOPE_API_KEY", "test-dashscope-secret")
    return isolated_manifest_env


@pytest.fixture
def fake_http_transport() -> Callable[
    [Callable[[httpx.Request], httpx.Response]], httpx.MockTransport
]:
    return httpx.MockTransport


def assert_provider_identity(
    identity: dict[str, Any],
    *,
    provider_type: str,
    model: str | None = None,
    voice: str | None = None,
) -> None:
    assert identity["configured"]["type"] == provider_type
    assert identity["resolved"]["type"] == provider_type
    assert identity["configured"].get("model") == model
    assert identity["resolved"].get("model") == model
    assert identity["configured"].get("voice") == voice
    assert identity["resolved"].get("voice") == voice
