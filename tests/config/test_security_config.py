from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from animetta.config.manifest import ManifestValidationError, load_effective_config
from animetta.config.security import SecurityConfig


def test_security_config_rejects_wildcard_origin() -> None:
    with pytest.raises(ValidationError, match="wildcard origins are forbidden"):
        SecurityConfig(allowed_origins=("*",))


def test_security_config_requires_https_for_non_loopback_origin() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        SecurityConfig(allowed_origins=("http://animetta.example",))


def test_security_config_accepts_exact_https_and_loopback_http() -> None:
    config = SecurityConfig(allowed_origins=("https://animetta.example", "http://127.0.0.1:8000"))

    assert config.allowed_origins == (
        "https://animetta.example",
        "http://127.0.0.1:8000",
    )
    assert config.display.allowed_origins == (
        "http://127.0.0.1",
        "http://localhost",
    )
    assert config.display.pairing_ttl_seconds == 300
    assert config.display.credential_days == 30


def test_schema_v1_is_rejected_for_production(
    tmp_path,
    manifest_data,
    isolated_manifest_env,
) -> None:
    manifest_data["schema_version"] = 1
    path = tmp_path / "animetta.yaml"
    path.write_text(yaml.safe_dump(manifest_data), encoding="utf-8")
    isolated_manifest_env.setenv("ANIMETTA_HOST", "127.0.0.1")
    isolated_manifest_env.setenv("ANIMETTA_PORT", "8000")

    with pytest.raises(ManifestValidationError, match="schema v2"):
        load_effective_config(path, profile="production")


def test_production_manifest_serializes_typed_pricing_date(monkeypatch) -> None:
    env = {
        "ANIMETTA_HOST": "127.0.0.1",
        "ANIMETTA_PORT": "12394",
        "DEEPSEEK_API_KEY": "test-deepseek",
        "MIMO_API_KEY": "test-mimo",
        "DASHSCOPE_API_KEY": "test-dashscope",
        "QWEN_TTS_API_KEY": "test-qwen",
        "QWEN_HOST_TTS_URL": "http://127.0.0.1:8767",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    effective = load_effective_config(Path("config/animetta.yaml"), profile="production")

    pricing = effective.providers["llm"].declaration["pricing"]
    assert pricing["verified_on"] == "2026-08-15"
    assert effective.runtime.enable_tools is True
    assert "http://127.0.0.1:12394" in effective.security.allowed_origins
    assert effective.security.display.max_active_credentials == 5
