from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from animetta.config import SceneAnalysisConfig
from animetta.config.manifest import ApplicationManifest, load_effective_config

pytestmark = pytest.mark.config_unit


@pytest.mark.parametrize("mode", ["off", "shadow", "active"])
def test_scene_analysis_accepts_exact_modes(mode: str) -> None:
    config = SceneAnalysisConfig(mode=mode)

    assert config.mode == mode


def test_scene_analysis_defaults_to_shadow_with_bounded_runtime_controls() -> None:
    config = SceneAnalysisConfig()

    assert config.mode == "shadow"
    assert config.reflection_interval_seconds == 30
    assert config.event_threshold == 30
    assert config.max_reflections_per_minute == 4
    assert config.guidance_wait_seconds == 0.3
    assert config.model_timeout_seconds == 5
    assert config.model_max_tokens == 800


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "enabled"},
        {"mode": "active", "event_threshold": 0},
        {"mode": "active", "unexpected": True},
    ],
)
def test_scene_analysis_rejects_invalid_or_unknown_settings(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SceneAnalysisConfig.model_validate(payload)


def test_application_manifest_canonicalizes_scene_analysis_snapshot() -> None:
    application = ApplicationManifest.model_validate(
        {
            "persona": "anima.v0.1",
            "system": {"host": "127.0.0.1", "port": 12394},
            "scene_analysis": {"mode": "active", "event_threshold": 20},
        }
    )

    assert application.scene_analysis["mode"] == "active"
    assert application.scene_analysis["event_threshold"] == 20
    assert application.manifest_dict()["scene_analysis"]["model_max_tokens"] == 800


def test_effective_config_projects_scene_settings_without_new_model_slot(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["application"]["scene_analysis"] = {
        "mode": "active",
        "reflection_interval_seconds": 15,
    }

    effective = load_effective_config(write_manifest(data), profile="production")

    assert effective.scene_analysis.mode == "active"
    assert effective.scene_analysis.reflection_interval_seconds == 15
    assert effective.services.llm == "deepseek"
    assert set(effective.providers) == {"llm", "asr", "tts", "vad"}
