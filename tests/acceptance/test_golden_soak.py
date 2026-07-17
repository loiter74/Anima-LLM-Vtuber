from __future__ import annotations

import json

import pytest

import animetta.acceptance.golden_soak as golden_soak
from animetta.acceptance.golden_soak import (
    EvidenceWriter,
    GateFailureError,
    TurnTracker,
    evaluate_degradation_budget,
    percentile,
    scan_sanitized_logs,
)
from scripts.soak_golden_path import _evaluate_media_completion, _is_connection_bootstrap


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


def test_incomplete_performance_failure_reports_missing_delivery_counts() -> None:
    tracker = complete_turn()
    tracker.action_count = 0

    with pytest.raises(
        GateFailureError,
        match=r"incomplete_performance_delivery:expression=1,action=0,terminal=1",
    ):
        tracker.finalize()


def test_streaming_turn_records_first_pcm_chunk_latency_and_validates_completion() -> None:
    tracker = TurnTracker(identity(), 0.0)
    tracker.accept("chat:sentence", {**identity(), "text": "旅人，晚上好。", "seq": 0}, 1.0)
    tracker.accept(
        "chat:sentence",
        {**identity(), "text": "", "seq": 1, "is_complete": True},
        1.1,
    )
    tracker.accept("chat:expression", {**identity(), "emotion": "happy"}, 1.2)
    tracker.accept("chat:live2d_action", {**identity(), "type": "motion"}, 1.3)
    tracker.accept(
        "chat:audio_stream_start",
        {
            **identity(),
            "stream_id": "stream-a",
            "format": "pcm_s16le",
            "sample_rate": 24_000,
            "channels": 1,
            "emotion": "happy",
        },
        1.35,
    )
    tracker.accept(
        "chat:audio_stream_chunk",
        {**identity(), "stream_id": "stream-a", "sequence": 0, "audio_data": "AAA="},
        1.4,
    )
    tracker.accept(
        "chat:audio_stream_chunk",
        {**identity(), "stream_id": "stream-a", "sequence": 1, "audio_data": "AAA="},
        1.42,
    )
    tracker.accept(
        "chat:audio_stream_end",
        {
            **identity(),
            "stream_id": "stream-a",
            "final_sequence": 1,
            "status": "completed",
        },
        1.45,
    )
    tracker.accept("chat:control", {**identity(), "signal": "conversation-end"}, 1.5)

    result = tracker.finalize()

    assert result["audio_ready_ms"] == 1400
    assert result["media_ready_ms"] == 1500
    assert result["audio_transport"] == "pcm_stream"
    assert result["audio_chunk_count"] == 2


def test_streaming_turn_rejects_duplicate_or_out_of_order_pcm_sequences() -> None:
    tracker = TurnTracker(identity(), 0.0)
    tracker.accept(
        "chat:audio_stream_start",
        {
            **identity(),
            "stream_id": "stream-a",
            "format": "pcm_s16le",
            "sample_rate": 24_000,
            "channels": 1,
            "emotion": "neutral",
        },
        0.1,
    )

    with pytest.raises(GateFailureError, match="audio_stream_sequence_mismatch"):
        tracker.accept(
            "chat:audio_stream_chunk",
            {**identity(), "stream_id": "stream-a", "sequence": 1, "audio_data": "AAA="},
            0.2,
        )


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
        (
            "用户问了一个关于休息的问题。我需要用Anima的身份来回答。",
            "roleplay_drift",
        ),
        ("用户表达了工作疲惫，需要安慰和共鸣。", "roleplay_drift"),
        (
            "旅人说工作累了。好感度50，礼貌有距离，但可以带点关心。",
            "roleplay_drift",
        ),
        (
            "用赛博酒馆的世界观来包装一下。好感度保持在50，礼貌有距离。",
            "roleplay_drift",
        ),
        (
            "The user is asking me to summarize our conversation. But wait, this is the first turn.",
            "roleplay_drift",
        ),
        (
            "这个问题偏哲学/生活类，不需要搜索。直接用自己的知识回答。",
            "roleplay_drift",
        ),
        (
            "保持轻毒舌+温柔收尾的风格。每条回复必须包含表情标签。",
            "roleplay_drift",
        ),
    ],
)
def test_drift_and_marker_checks(text: str, reason: str) -> None:
    tracker = complete_turn()
    tracker.final_text = text
    with pytest.raises(GateFailureError, match=reason):
        tracker.finalize()


@pytest.mark.parametrize(
    "text",
    [
        "Let me pour you another drink, traveler.",
        "I should know—this is my tavern.",
        "Let me use the user's map; the cellar is this way, traveler.",
        "I should consider the user's debt paid; this round is on me.",
    ],
)
def test_golden_soak_accepts_legitimate_english_character_dialogue(text: str) -> None:
    tracker = complete_turn()
    tracker.final_text = text

    result = tracker.finalize()

    assert result["drift"] == []


def test_percentile_uses_nearest_rank() -> None:
    assert percentile(list(range(1, 101)), 95) == 95


def test_media_completion_can_be_report_only_for_streaming_tts_gate() -> None:
    turns = [{"media_ready_ms": 22_000.0, "degraded": False}]

    enforced = _evaluate_media_completion(turns, limit_ms=20_000.0)
    report_only = _evaluate_media_completion(turns, limit_ms=0.0)

    assert enforced == {
        "p95_ms": 22_000.0,
        "limit_ms": 20_000.0,
        "enforced": True,
        "passed": False,
    }
    assert report_only == {
        "p95_ms": 22_000.0,
        "limit_ms": None,
        "enforced": False,
        "passed": True,
    }


def test_audio_latency_gate_requires_every_turn_and_enforces_p50_p95() -> None:
    evaluate_audio_latency = getattr(golden_soak, "evaluate_audio_latency")
    passing = evaluate_audio_latency(
        [{"audio_ready_ms": value} for value in (900, 1200, 1800, 2400, 4800)],
        p50_limit_ms=3000,
        p95_limit_ms=5000,
    )
    incomplete = evaluate_audio_latency(
        [{"audio_ready_ms": 1000}, {"audio_ready_ms": None}],
        p50_limit_ms=3000,
        p95_limit_ms=5000,
    )

    assert passing == {
        "turn_count": 5,
        "sample_count": 5,
        "p50_ms": 1800.0,
        "p95_ms": 4800.0,
        "p50_limit_ms": 3000.0,
        "p95_limit_ms": 5000.0,
        "complete": True,
        "passed": True,
    }
    assert incomplete["complete"] is False
    assert incomplete["passed"] is False


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
