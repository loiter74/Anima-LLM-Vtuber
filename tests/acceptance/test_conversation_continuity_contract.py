"""Deterministic tests for the content-free continuity evidence contract."""

from __future__ import annotations

import json
from dataclasses import replace

from animetta.acceptance.conversation_continuity import (
    EXPECTATIONS,
    ContinuityStepEvidence,
    ContinuityStepId,
    build_sanitized_evidence,
    validate_continuity_steps,
)


def _valid_steps() -> tuple[ContinuityStepEvidence, ...]:
    return tuple(
        ContinuityStepEvidence(
            step_id=step_id,
            trace_id=f"trace-{index}",
            scope_kind=expectation.scope_kind,
            window_before=expectation.window_before,
            window_after=expectation.window_after,
            committed=expectation.committed,
            actor_role=expectation.actor_role,
            source=expectation.source,
            public_fact_recalled=(
                True
                if step_id
                in {
                    ContinuityStepId.VIEWER_REPLY,
                    ContinuityStepId.DEVELOPER_FOLLOWUP,
                }
                else None
            ),
            private_marker_absent=(
                True
                if step_id
                in {
                    ContinuityStepId.VIEWER_REPLY,
                    ContinuityStepId.DEVELOPER_FOLLOWUP,
                }
                else None
            ),
        )
        for index, (step_id, expectation) in enumerate(EXPECTATIONS.items())
    )


def test_canonical_transitions_validate_without_duplicate_assertions() -> None:
    assert validate_continuity_steps(_valid_steps()) == ()


def test_transition_errors_use_stable_codes() -> None:
    steps = list(_valid_steps())
    steps[1] = replace(steps[1], committed=True)
    steps[2] = replace(steps[2], public_fact_recalled=False)
    steps[3] = replace(steps[3], private_marker_absent=False)

    assert validate_continuity_steps(steps) == (
        "transition_mismatch:replay_probe:committed",
        "public_fact_not_recalled:viewer_reply",
        "private_marker_leaked:developer_followup",
    )


def test_sanitized_evidence_contains_no_conversation_content_fields() -> None:
    evidence = build_sanitized_evidence(
        run_id="continuity-run",
        provider_real=True,
        socket_recreated=True,
        steps=_valid_steps(),
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "passed"
    assert evidence["error_codes"] == []
    for forbidden in (
        "user_text",
        "response_text",
        "history",
        "messages",
        "PUBLIC-SECRET",
        "PRIVATE-SECRET",
    ):
        assert forbidden not in serialized


def test_failed_environment_checks_fail_closed() -> None:
    evidence = build_sanitized_evidence(
        run_id="continuity-run",
        provider_real=False,
        socket_recreated=False,
        steps=_valid_steps(),
    )

    assert evidence["status"] == "failed"
    assert evidence["error_codes"] == ["mock_provider", "socket_reconnect_failed"]
