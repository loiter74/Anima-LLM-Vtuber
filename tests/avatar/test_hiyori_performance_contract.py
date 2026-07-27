from __future__ import annotations

import json
from pathlib import Path

from animetta.avatar.mappers.emotion_param_mapper import (
    DEFAULT_EMOTION_MAPPINGS,
    EmotionParamMapper,
)

ROOT = Path(__file__).parents[2]
HIYORI_DIR = ROOT / "frontend" / "public" / "live2d" / "hiyori"


def test_hiyori_idle_contains_only_calm_m01_and_tap_body_is_unchanged() -> None:
    manifest = json.loads((HIYORI_DIR / "Hiyori.model3.json").read_text(encoding="utf-8"))
    motions = manifest["FileReferences"]["Motions"]

    assert [motion["File"] for motion in motions["Idle"]] == ["motions/Hiyori_m01.motion3.json"]
    assert [motion["File"] for motion in motions["TapBody"]] == ["motions/Hiyori_m04.motion3.json"]


def test_legacy_mapper_uses_real_hiyori_parameters_without_mouth_open() -> None:
    display = json.loads((HIYORI_DIR / "Hiyori.cdi3.json").read_text(encoding="utf-8"))
    parameter_ids = {parameter["Id"] for parameter in display["Parameters"]}
    mapped_ids = {
        parameter_id for mapping in DEFAULT_EMOTION_MAPPINGS.values() for parameter_id in mapping
    }

    assert "ParamMouthOpenY" not in mapped_ids
    assert not {name for name in mapped_ids if name.startswith("ParamEyebrow")}
    assert mapped_ids <= parameter_ids


def test_legacy_mapper_is_deterministic() -> None:
    mapper = EmotionParamMapper()

    first = mapper.map_emotion("thinking", intensity=0.7)
    second = mapper.map_emotion("thinking", intensity=0.7)

    assert first.parameters == second.parameters
