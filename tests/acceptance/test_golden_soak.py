from __future__ import annotations

import json

import pytest

from animetta.acceptance.golden_soak import (
    EvidenceWriter,
    GateFailureError,
    TurnTracker,
    evaluate_degradation_budget,
    percentile,
    scan_sanitized_logs,
)
from scripts.soak_golden_path import _is_connection_bootstrap


def identity() -> dict[str, str]:
    return {
        "message_id": "m",
        "conversation_id": "c",
        "task_id": "t",
        "turn_id": "t",
    }


def test_only_legacy_start_mic_control_is_connection_bootstrap() -> None:
    assert _is_connection_bootstrap("chat:control", {"type": "control", "text": "start-mic"})
    assert not _is_connection_bootstrap("chat:control", {"signal": "conversation-end"})
    assert not _is_connection_bootstrap("chat:sentence", {"text": "orphan"})


def complete_turn(*, degraded: bool = False) -> TurnTracker:
    tracker = TurnTracker(identity(), 0.0)
    tracker.accept("chat:sentence", {**identity(), "text": "旅人，晚上好。", "seq": 0}, 1.0)
    tracker.accept("chat:sentence", {**identity(), "text": "", "seq": 1, "is_complete": True}, 1.1)
    tracker.accept("chat:expression", {**identity(), "emotion": "happy"}, 1.2)
    tracker.accept("chat:live2d_action", {**identity(), "type": "motion"}, 1.3)
    if degraded:
        tracker.accept(
            "chat:control",
            {
                **identity(),
                "type": "media-degraded",
                "status": "degraded",
                "component": "tts",
                "reason": "timeout",
            },
            1.4,
        )
    else:
        tracker.accept(
            "chat:audio_with_expression",
            {
                **identity(),
                "audio_data": "UklGRg==",
                "format": "wav",
                "volumes": [0.2],
            },
            1.4,
        )
    tracker.accept("chat:control", {**identity(), "signal": "conversation-end"}, 1.5)
    return tracker


def test_turn_state_machine_proves_complete_correlated_turn() -> None:
    result = complete_turn().finalize()
    assert result["text_ready_ms"] == 1000
    assert result["media_ready_ms"] == 1500
    assert result["degraded"] is False


def test_identity_mismatch_and_duplicate_text_fail() -> None:
    tracker = TurnTracker(identity(), 0)
    with pytest.raises(GateFailureError, match="identity_mismatch"):
        tracker.accept("chat:sentence", {**identity(), "task_id": "other", "text": "x"}, 1)
    tracker.accept("chat:sentence", {**identity(), "text": "one"}, 1)
    with pytest.raises(GateFailureError, match="duplicate_authored"):
        tracker.accept("chat:sentence", {**identity(), "text": "two"}, 2)


@pytest.mark.parametrize(
    "text,reason",
    [
        ("作为 AI，我建议你休息。", "roleplay_drift"),
        ("[affinity:2] 你好", "runtime_marker_leak"),
    ],
)
def test_drift_and_marker_checks(text: str, reason: str) -> None:
    tracker = complete_turn()
    tracker.final_text = text
    with pytest.raises(GateFailureError, match=reason):
        tracker.finalize()


def test_percentile_uses_nearest_rank() -> None:
    assert percentile(list(range(1, 101)), 95) == 95


def test_degradation_budget_requires_recovery_and_rejects_repeat() -> None:
    assert evaluate_degradation_budget(
        [
            {"degraded": True},
            {"degraded": False},
        ]
    )[0]
    assert not evaluate_degradation_budget([{"degraded": True}])[0]
    assert not evaluate_degradation_budget(
        [
            {"degraded": True},
            {"degraded": True},
            {"degraded": False},
        ]
    )[0]


def test_log_scan_allows_typed_warning_but_rejects_fatal_patterns() -> None:
    assert scan_sanitized_logs("WARNING media-degraded component=tts") == []
    violations = scan_sanitized_logs("ERROR boom\nTraceback\nMockTTS selected")
    assert len(violations) == 3


def test_evidence_writer_flushes_before_failure(tmp_path) -> None:
    path = tmp_path / "evidence.json"
    writer = EvidenceWriter(path, {"status": "running", "turns": []})
    writer.append_turn({"identity": identity()})
    assert path.exists()
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored["turns"][0]["identity"]["task_id"] == "t"
