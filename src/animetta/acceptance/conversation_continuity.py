"""Content-free contract for livestream conversation continuity evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ContinuityStepId(StrEnum):
    """Stable identifiers for the canonical livestream continuity scenario."""

    DEVELOPER_SEED = "developer_seed"
    REPLAY_PROBE = "replay_probe"
    VIEWER_REPLY = "viewer_reply"
    DEVELOPER_FOLLOWUP = "developer_followup"


@dataclass(frozen=True, slots=True)
class ContinuityExpectation:
    scope_kind: str
    window_before: int
    window_after: int
    committed: bool
    actor_role: str
    source: str


EXPECTATIONS: Mapping[ContinuityStepId, ContinuityExpectation] = {
    ContinuityStepId.DEVELOPER_SEED: ContinuityExpectation(
        scope_kind="livestream",
        window_before=0,
        window_after=1,
        committed=True,
        actor_role="developer",
        source="developer_console",
    ),
    ContinuityStepId.REPLAY_PROBE: ContinuityExpectation(
        scope_kind="livestream",
        window_before=1,
        window_after=1,
        committed=False,
        actor_role="viewer",
        source="bilibili:danmaku",
    ),
    ContinuityStepId.VIEWER_REPLY: ContinuityExpectation(
        scope_kind="livestream",
        window_before=1,
        window_after=2,
        committed=True,
        actor_role="viewer",
        source="bilibili:danmaku",
    ),
    ContinuityStepId.DEVELOPER_FOLLOWUP: ContinuityExpectation(
        scope_kind="livestream",
        window_before=2,
        window_after=3,
        committed=True,
        actor_role="developer",
        source="developer_console",
    ),
}


@dataclass(frozen=True, slots=True)
class ContinuityStepEvidence:
    """One sanitized trace transition; conversation content is intentionally absent."""

    step_id: ContinuityStepId
    trace_id: str
    scope_kind: str
    window_before: int
    window_after: int
    committed: bool
    actor_role: str
    source: str
    public_fact_recalled: bool | None = None
    private_marker_absent: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "step_id": self.step_id.value}


def validate_continuity_steps(steps: Sequence[ContinuityStepEvidence]) -> tuple[str, ...]:
    """Return stable error codes for deviations from the canonical scenario."""

    errors: list[str] = []
    expected_ids = tuple(EXPECTATIONS)
    actual_ids = tuple(step.step_id for step in steps)
    if actual_ids != expected_ids:
        errors.append("step_sequence_mismatch")

    indexed = {step.step_id: step for step in steps}
    if len(indexed) != len(steps):
        errors.append("duplicate_step")
    for step_id, expected in EXPECTATIONS.items():
        step = indexed.get(step_id)
        if step is None:
            errors.append(f"missing_step:{step_id.value}")
            continue
        for field in (
            "scope_kind",
            "window_before",
            "window_after",
            "committed",
            "actor_role",
            "source",
        ):
            if getattr(step, field) != getattr(expected, field):
                errors.append(f"transition_mismatch:{step_id.value}:{field}")

    for step_id in (ContinuityStepId.VIEWER_REPLY, ContinuityStepId.DEVELOPER_FOLLOWUP):
        step = indexed.get(step_id)
        if step is None:
            continue
        if step.public_fact_recalled is not True:
            errors.append(f"public_fact_not_recalled:{step_id.value}")
        if step.private_marker_absent is not True:
            errors.append(f"private_marker_leaked:{step_id.value}")
    return tuple(errors)


def build_sanitized_evidence(
    *,
    run_id: str,
    provider_real: bool,
    socket_recreated: bool,
    steps: Sequence[ContinuityStepEvidence],
) -> dict[str, Any]:
    """Build the only evidence shape allowed to leave a continuity run."""

    errors = list(validate_continuity_steps(steps))
    if not provider_real:
        errors.append("mock_provider")
    if not socket_recreated:
        errors.append("socket_reconnect_failed")
    return {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "run_id": run_id,
        "provider_real": provider_real,
        "socket_recreated": socket_recreated,
        "steps": [step.to_dict() for step in steps],
        "error_codes": errors,
    }
