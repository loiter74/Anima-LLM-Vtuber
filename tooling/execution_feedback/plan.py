from __future__ import annotations

from collections.abc import Callable, Mapping

from .models import (
    ExecutionPlanManifest,
    FeedbackStatus,
    PlanAggregate,
    PlanAggregateStatus,
    PlanRecovery,
    PlanStepCheckpoint,
    validate_sha256,
)
from .store import IterationPlanStore


class PlanRecoveryManager:
    def __init__(self, store: IterationPlanStore) -> None:
        self._store = store

    def persist_plan(self, plan: ExecutionPlanManifest) -> None:
        self._store.write_plan(plan)

    def record(self, checkpoint: PlanStepCheckpoint) -> None:
        self._store.write_checkpoint(checkpoint)

    def recover(
        self,
        plan: ExecutionPlanManifest,
        *,
        expected_fingerprints: Mapping[str, str],
        evidence_exists: Callable[[str], bool],
    ) -> PlanRecovery:
        known_steps = {step.id for step in plan.steps}
        if set(expected_fingerprints) != known_steps:
            raise ValueError("expected fingerprints must match the frozen plan steps")
        for fingerprint in expected_fingerprints.values():
            validate_sha256(fingerprint, field_name="expected fingerprint")

        by_id = {step.id: step for step in plan.steps}
        invalidated: dict[str, str] = {}
        reusable: set[str] = set()

        def evaluate(step_id: str) -> bool:
            if step_id in reusable:
                return True
            if step_id in invalidated:
                return False
            step = by_id[step_id]
            for dependency in step.depends_on:
                if not evaluate(dependency):
                    invalidated[step_id] = f"dependency {dependency} is invalid"
                    return False

            checkpoint = self._store.read_checkpoint(plan.run_id, step_id)
            if checkpoint is None:
                invalidated[step_id] = "checkpoint is missing or invalid"
                return False
            if checkpoint.reuse_fingerprint != expected_fingerprints[step_id]:
                invalidated[step_id] = "reuse fingerprint changed"
                return False
            references = (*checkpoint.evidence_refs, checkpoint.result_reference)
            if not all(evidence_exists(reference) for reference in references):
                invalidated[step_id] = "checkpoint evidence is missing"
                return False
            reusable.add(step_id)
            return True

        for step in plan.steps:
            evaluate(step.id)

        continuation_results = tuple(
            recovery.result
            for step in plan.steps
            if (recovery := self._store.recover_latest_result(plan.run_id, step.id)).result
            is not None
        )
        return PlanRecovery(
            reusable_steps=tuple(step.id for step in plan.steps if step.id in reusable),
            invalidated_steps={
                step.id: invalidated[step.id] for step in plan.steps if step.id in invalidated
            },
            continuation_results=continuation_results,
        )


def aggregate_plan_status(
    plan: ExecutionPlanManifest,
    statuses: Mapping[str, FeedbackStatus],
) -> PlanAggregate:
    required = tuple(step for step in plan.steps if step.required)
    nonpassing = tuple(
        step.id for step in required if statuses.get(step.id) is not FeedbackStatus.PASSED
    )
    if not nonpassing:
        status = PlanAggregateStatus.PASSED
    elif any(statuses.get(step_id) in {None, FeedbackStatus.IN_PROGRESS} for step_id in nonpassing):
        status = PlanAggregateStatus.IN_PROGRESS
    elif any(
        statuses.get(step_id) in {FeedbackStatus.FAILED, FeedbackStatus.TIMED_OUT}
        for step_id in nonpassing
    ):
        status = PlanAggregateStatus.FAILED
    else:
        status = PlanAggregateStatus.BLOCKED
    return PlanAggregate(status=status, nonpassing_required_steps=nonpassing)
