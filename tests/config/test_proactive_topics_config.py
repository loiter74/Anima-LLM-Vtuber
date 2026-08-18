"""Contracts for proactive livestream topic configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.config.manifest import (
    ApplicationManifest,
    ApplicationSystem,
    load_effective_config,
)
from animetta.config.proactive_topics import ProactiveTopicsConfig


def test_defaults_remain_disabled_for_older_manifests() -> None:
    config = ProactiveTopicsConfig()

    assert config.enabled is False
    assert config.initial_silence_seconds == 60
    assert config.interval_min_seconds == 90
    assert config.interval_max_seconds == 180
    assert config.max_chars == 36


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("initial_silence_seconds", 0),
        ("interval_min_seconds", 0),
        ("interval_max_seconds", 0),
        ("max_chars", 1),
        ("max_chars", 37),
    ],
)
def test_rejects_out_of_range_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        ProactiveTopicsConfig.model_validate({field: value})


def test_rejects_inverted_interval_range_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        ProactiveTopicsConfig(interval_min_seconds=181, interval_max_seconds=180)
    with pytest.raises(ValidationError):
        ProactiveTopicsConfig.model_validate({"unexpected": True})


def test_application_manifest_exposes_an_immutable_snapshot() -> None:
    application = ApplicationManifest(
        persona="anima",
        system=ApplicationSystem(host="127.0.0.1", port=8000),
        proactive_topics={"enabled": True},
    )

    assert application.proactive_topics["enabled"] is True
    assert application.proactive_topics["max_chars"] == 36
    assert application.manifest_dict()["proactive_topics"]["interval_min_seconds"] == 90


def test_formal_manifest_explicitly_enables_proactive_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANIMETTA_HOST", "127.0.0.1")
    monkeypatch.setenv("ANIMETTA_PORT", "12394")

    config = load_effective_config(profile="test")

    assert config.proactive_topics == ProactiveTopicsConfig(enabled=True)
