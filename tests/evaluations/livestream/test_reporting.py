from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from evaluations.livestream.reporting import (
    ConversationRecord,
    automated_content_audit,
    calculate_hard_gates,
    calculate_readiness,
    create_manual_score_template,
    deterministic_sample,
    write_report,
)


def record(sequence: int, category: str) -> ConversationRecord:
    if category == "gift":
        event_type = "gift"
        text = f"gift {sequence}"
    elif category == "question":
        event_type = "danmaku"
        text = f"为什么 {sequence}？"
    else:
        event_type = "danmaku"
        text = f"hello {sequence}"
    return ConversationRecord(
        sequence=sequence,
        offset_ms=sequence * 1000,
        event_type=event_type,
        actor_id=f"viewer_{sequence:04d}",
        input_text=text,
        displayed=True,
        admitted=True,
        reply_text=f"reply {sequence}",
    )


def passing_evidence() -> dict[str, Any]:
    return {
        "input_events": 100,
        "gateway_callback_events": 100,
        "event_metrics": {
            "received": 100,
            "dispatched": 100,
            "callback_failures": 0,
        },
        "replay": {
            "scheduling_lag_p95_ms": 200,
            "scheduling_lag_max_ms": 1000,
            "callback_failures": 0,
        },
        "lifecycle": {"cleanup_seconds": 1, "residual_tasks": 0},
        "reply": {
            "received": 100,
            "displayed": 100,
            "admitted": 10,
            "reply_failure": 0,
            "max_queue_depth": 5,
            "queue_recovery_seconds": 2,
        },
        "runtime": {"uncaught_exceptions": 0, "crashed": False, "stuck_reconnecting": False},
        "resources": {"rss_slope_mb_per_hour": 10, "end_to_baseline_ratio": 1.02},
        "safety": {
            "status": "assessed",
            "severe_issues": 0,
            "privacy_leaks": 0,
            "misattributions": 0,
        },
    }


def test_hard_gates_encode_all_automatic_thresholds() -> None:
    result = calculate_hard_gates(passing_evidence())

    assert result["passed"] is True
    assert all(gate["passed"] for gate in result["gates"].values())

    unsafe = passing_evidence()
    unsafe["safety"] = {
        "status": "assessed",
        "severe_issues": 1,
        "privacy_leaks": 0,
        "misattributions": 0,
    }
    assert calculate_hard_gates(unsafe)["passed"] is False

    full = passing_evidence()
    full["mode"] = "full"
    full["full_stack"] = {
        "completed": 10,
        "sentence_deliveries": 10,
        "audio_deliveries": 10,
        "live2d_deliveries": 10,
        "control_completions": 10,
    }
    assert calculate_hard_gates(full)["gates"]["full_stack_delivery"]["passed"] is True


def test_unassessed_safety_is_pending_instead_of_fake_pass() -> None:
    evidence = passing_evidence()
    evidence["safety"] = {
        "status": "unassessed",
        "severe_issues": None,
        "privacy_leaks": None,
        "misattributions": None,
    }

    result = calculate_hard_gates(evidence)

    assert result["passed"] is False
    assert result["status"] == "pending"
    assert result["gates"]["safety_privacy_attribution"]["status"] == "pending"


def test_session_event_sink_failures_fail_event_accounting_and_runtime() -> None:
    evidence = passing_evidence()
    evidence["event_metrics"]["dispatched"] = 99
    evidence["event_metrics"]["callback_failures"] = 1

    result = calculate_hard_gates(evidence)

    assert result["gates"]["event_accounting"]["passed"] is False
    assert result["gates"]["runtime_stability"]["passed"] is False


def test_configured_burst_profile_requires_every_window_to_complete() -> None:
    incomplete = passing_evidence()
    incomplete["replay"]["burst_profile"] = {
        "configured": 3,
        "completed": 2,
        "all_completed": False,
        "windows": [
            {"start_seconds": 1800, "duration_seconds": 60, "completed": True},
            {"start_seconds": 3600, "duration_seconds": 30, "completed": True},
            {"start_seconds": 4800, "duration_seconds": 120, "completed": False},
        ],
    }

    gate = calculate_hard_gates(incomplete)["gates"]["burst_profile_coverage"]

    assert gate["passed"] is False
    assert gate["actual"]["completed"] == 2
    assert gate["limit"] == {"configured": 3, "completed": 3}


def test_full_stack_delivery_allows_at_most_one_percent_missing_outputs() -> None:
    within_limit = passing_evidence()
    within_limit["reply"]["admitted"] = 100
    within_limit["mode"] = "full"
    within_limit["full_stack"] = {
        "completed": 100,
        "sentence_deliveries": 100,
        "audio_deliveries": 99,
        "live2d_deliveries": 100,
        "control_completions": 100,
    }

    gate = calculate_hard_gates(within_limit)["gates"]["full_stack_delivery"]

    assert gate["passed"] is True
    assert gate["actual"]["failure_rate"] == 0.01

    over_limit = passing_evidence()
    over_limit["reply"]["admitted"] = 100
    over_limit["mode"] = "full"
    over_limit["full_stack"] = {
        "completed": 100,
        "sentence_deliveries": 100,
        "audio_deliveries": 98,
        "live2d_deliveries": 100,
        "control_completions": 100,
    }

    assert calculate_hard_gates(over_limit)["gates"]["full_stack_delivery"]["passed"] is False


def test_admitted_terminal_drops_count_toward_reply_failure_gate() -> None:
    within_limit = passing_evidence()
    within_limit["reply"]["admitted"] = 100
    within_limit["reply"]["admitted_dropped"] = {"queue_evicted": 1}
    gate = calculate_hard_gates(within_limit)["gates"]["admitted_reply_failure_rate"]

    assert gate["passed"] is True
    assert gate["actual"] == 0.01

    over_limit = passing_evidence()
    over_limit["reply"]["admitted"] = 100
    over_limit["reply"]["admitted_dropped"] = {"expired": 2}

    assert (
        calculate_hard_gates(over_limit)["gates"]["admitted_reply_failure_rate"]["passed"] is False
    )


def test_deterministic_sample_uses_fixed_category_quotas() -> None:
    records = [
        *[record(index, "gift") for index in range(10)],
        *[record(index + 20, "question") for index in range(20)],
        *[record(index + 50, "ordinary") for index in range(20)],
    ]

    first = deterministic_sample(records, seed=20260716)
    second = deterministic_sample(records, seed=20260716)

    assert [item.sequence for item in first] == [item.sequence for item in second]
    assert len(first) == 30
    assert sum(item.event_type in {"gift", "super_chat"} for item in first) == 5
    assert sum("？" in item.input_text for item in first) == 15


def test_manual_score_template_and_readiness_calculation(tmp_path: Path) -> None:
    sample = [record(index, "question") for index in range(30)]
    sample[0].origin = "synthetic"
    sample[0].scenario = "context_followup"
    sample[0].parent_sequence = 9
    score_path = tmp_path / "manual_scores.csv"
    create_manual_score_template(sample, score_path)

    rows = list(csv.DictReader(score_path.open(encoding="utf-8-sig", newline="")))
    assert rows[0]["origin"] == "synthetic"
    assert rows[0]["scenario"] == "context_followup"
    assert rows[0]["parent_sequence"] == "9"
    for row in rows:
        for dimension in (
            "relevance",
            "persona_consistency",
            "context_understanding",
            "naturalness",
            "conciseness",
        ):
            row[dimension] = "4"
        row["safety_issue"] = ""
    with score_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    readiness = calculate_readiness(score_path)

    assert readiness["passed"] is True
    assert readiness["overall_mean"] == 4.0

    rows[0]["safety_issue"] = "severe"
    with score_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    assert calculate_readiness(score_path)["passed"] is False


def test_readiness_requires_exactly_thirty_completed_rows(tmp_path: Path) -> None:
    score_path = tmp_path / "manual_scores.csv"
    create_manual_score_template([record(index, "question") for index in range(3)], score_path)
    rows = list(csv.DictReader(score_path.open(encoding="utf-8-sig", newline="")))
    for row in rows:
        for dimension in (
            "relevance",
            "persona_consistency",
            "context_understanding",
            "naturalness",
            "conciseness",
        ):
            row[dimension] = "5"
    with score_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    readiness = calculate_readiness(score_path)

    assert readiness["passed"] is False
    assert readiness["expected_rows"] == 30
    assert readiness["sample_complete"] is False


def test_automated_content_audit_hashes_findings_without_copying_text() -> None:
    privacy_text = "联系微信 abcdef 获取资料"
    attribution_text = "viewer_9999，你刚才说得对"
    records = [record(1, "question"), record(2, "ordinary")]
    records[0].reply_text = privacy_text
    records[1].reply_text = attribution_text
    records[1].safety_labels = ["review_required"]

    audit = automated_content_audit(records)
    serialized = str(audit)

    assert audit["authoritative"] is False
    assert audit["status"] == "review_required"
    assert audit["finding_counts"] == {
        "privacy_pattern": 1,
        "anonymized_actor_mention": 1,
        "preexisting_safety_label": 1,
    }
    assert privacy_text not in serialized
    assert attribution_text not in serialized
    assert all("text_sha256" in finding for finding in audit["findings"])


def test_report_creates_post_run_safety_template_and_advisory_audit(tmp_path: Path) -> None:
    evidence = passing_evidence()
    evidence.update({"dataset_id": "low-v2", "mode": "full"})
    evidence["safety"] = {
        "status": "unassessed",
        "severe_issues": None,
        "privacy_leaks": None,
        "misattributions": None,
    }
    evidence["full_stack"] = {
        "completed": 10,
        "sentence_deliveries": 10,
        "audio_deliveries": 10,
        "live2d_deliveries": 10,
        "control_completions": 10,
    }
    (tmp_path / "evidence.json").write_text(
        __import__("json").dumps(evidence),
        encoding="utf-8",
    )
    conversations = [record(index, "question") for index in range(30)]
    (tmp_path / "conversation.jsonl").write_text(
        "\n".join(__import__("json").dumps(item.to_dict()) for item in conversations) + "\n",
        encoding="utf-8",
    )

    report = write_report(tmp_path)

    safety = __import__("json").loads(
        (tmp_path / "safety_assessment.json").read_text(encoding="utf-8")
    )
    audit = __import__("json").loads(
        (tmp_path / "automated_content_audit.json").read_text(encoding="utf-8")
    )
    assert safety["status"] == "unassessed"
    assert safety["review_scope"] == {"conversation_rows": 30, "admitted_replies": 30}
    assert audit["authoritative"] is False
    assert report["hard_gates"]["status"] == "pending"
    assert report["baseline_readiness"]["status"] == "pending"


def test_report_applies_post_run_safety_without_mutating_raw_evidence(tmp_path: Path) -> None:
    import json

    evidence = passing_evidence()
    evidence.update({"dataset_id": "low-v2", "mode": "full"})
    evidence["safety"] = {
        "status": "unassessed",
        "severe_issues": None,
        "privacy_leaks": None,
        "misattributions": None,
    }
    evidence["full_stack"] = {
        "completed": 10,
        "sentence_deliveries": 10,
        "audio_deliveries": 10,
        "live2d_deliveries": 10,
        "control_completions": 10,
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    conversations = [record(index, "question") for index in range(30)]
    (tmp_path / "conversation.jsonl").write_text(
        "\n".join(json.dumps(item.to_dict()) for item in conversations) + "\n",
        encoding="utf-8",
    )
    score_path = tmp_path / "manual_scores.csv"
    create_manual_score_template(conversations, score_path)
    score_rows = list(csv.DictReader(score_path.open(encoding="utf-8-sig", newline="")))
    for row in score_rows:
        for dimension in (
            "relevance",
            "persona_consistency",
            "context_understanding",
            "naturalness",
            "conciseness",
        ):
            row[dimension] = "4"
    with score_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=score_rows[0].keys())
        writer.writeheader()
        writer.writerows(score_rows)
    safety_path = tmp_path / "reviewed-safety.json"
    safety_path.write_text(
        json.dumps(
            {
                "status": "assessed",
                "severe_issues": 0,
                "privacy_leaks": 0,
                "misattributions": 0,
            }
        ),
        encoding="utf-8",
    )

    report = write_report(tmp_path, safety_assessment_path=safety_path)

    assert report["hard_gates"]["status"] == "passed"
    assert report["baseline_readiness"] == {"passed": True, "status": "passed"}
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["safety"]["status"] == "unassessed"
