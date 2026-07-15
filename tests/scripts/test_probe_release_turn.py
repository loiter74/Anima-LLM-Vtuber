from __future__ import annotations

import pytest

from scripts.probe_release_turn import ReleaseTurnProbeError, validate_turn_result


def test_release_turn_probe_requires_typed_degradation_with_text_and_live2d() -> None:
    result = {
        "degraded": True,
        "audio_count": 0,
        "degradation_count": 1,
        "expression_count": 1,
        "action_count": 1,
        "safe_output": "仍然保留文字回复。",
    }

    validate_turn_result(result, expect="degraded")

    result["action_count"] = 0
    with pytest.raises(ReleaseTurnProbeError, match="Live2D"):
        validate_turn_result(result, expect="degraded")


def test_release_turn_probe_requires_audio_on_same_provider_retry() -> None:
    result = {
        "degraded": False,
        "audio_count": 1,
        "degradation_count": 0,
        "expression_count": 1,
        "action_count": 1,
        "safe_output": "语音已经恢复。",
    }

    validate_turn_result(result, expect="audio")

    result["audio_count"] = 0
    with pytest.raises(ReleaseTurnProbeError, match="audio"):
        validate_turn_result(result, expect="audio")
