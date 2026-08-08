from __future__ import annotations

import json
from pathlib import Path

from animetta.avatar.mappers.emotion_param_mapper import (
    DEFAULT_EMOTION_MAPPINGS,
    EmotionParamMapper,
)

ROOT = Path(__file__).parents[2]
MAO_DIR = ROOT / "frontend" / "public" / "live2d" / "mao"


def test_mao_manifest_declares_native_lip_sync_and_blink_parameters() -> None:
    manifest = json.loads((MAO_DIR / "Mao.model3.json").read_text(encoding="utf-8"))
    groups = {group["Name"]: group["Ids"] for group in manifest["Groups"]}

    assert groups["LipSync"] == ["ParamA"]
    assert groups["EyeBlink"] == ["ParamEyeLOpen", "ParamEyeROpen"]


def test_legacy_mapper_parameters_are_native_or_use_the_mouth_shape_alias() -> None:
    display = json.loads((MAO_DIR / "Mao.cdi3.json").read_text(encoding="utf-8"))
    parameter_ids = {parameter["Id"] for parameter in display["Parameters"]}
    mapped_ids = {
        parameter_id for mapping in DEFAULT_EMOTION_MAPPINGS.values() for parameter_id in mapping
    }

    assert "ParamA" not in mapped_ids
    assert not {name for name in mapped_ids if name.startswith("ParamEyebrow")}
    assert mapped_ids - {"ParamMouthForm"} <= parameter_ids
    assert {"ParamMouthUp", "ParamMouthDown"} <= parameter_ids


def test_legacy_mapper_is_deterministic() -> None:
    mapper = EmotionParamMapper()

    first = mapper.map_emotion("thinking", intensity=0.7)
    second = mapper.map_emotion("thinking", intensity=0.7)

    assert first.parameters == second.parameters
