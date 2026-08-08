from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import Field, model_validator

from tooling.execution_feedback import FeedbackStatus

from .models import (
    Capability,
    DominatedGroup,
    FrozenModel,
    PlannedGroup,
    ResultStatus,
    SchedulerPolicy,
    VerificationPlan,
    VerificationResult,
)
from .scheduler import run_schedule

_MAX_ACTION_SECONDS = 239.0
_MAX_COMMAND_CHARACTERS = 24_000


class QualityShardSpec(FrozenModel):
    plan_hash: str
    manifest_hash: str
    group_id: str
    shard_id: str
    root_shard_id: str
    sequence: int = Field(ge=1)
    continuation_sequence: int = Field(default=0, ge=0)
    operation: Literal["test", "coverage"] = "test"
    opaque: bool = False
    test_ids: tuple[str, ...]
    estimated_test_seconds: tuple[float, ...]
    estimated_seconds: float = Field(gt=0, lt=240)
    action_budget_seconds: float = Field(default=_MAX_ACTION_SECONDS, gt=0, lt=240)
    depends_on: tuple[str, ...]
    capabilities: frozenset[Capability]
    cacheable: bool
    input_fingerprint: str

    @model_validator(mode="after")
    def validate_tests(self) -> QualityShardSpec:
        if len(self.test_ids) != len(self.estimated_test_seconds):
            raise ValueError("test IDs and estimates must have equal lengths")
        if any(estimate <= 0 for estimate in self.estimated_test_seconds):
            raise ValueError("test estimates must be positive")
        if len(set(self.test_ids)) != len(self.test_ids):
            raise ValueError("test IDs in a shard must be unique")
        return self


class QualityFeedbackPlan(FrozenModel):
    schema_version: int = 1
    plan_hash: str
    manifest_hash: str
    groups: tuple[PlannedGroup, ...]
    required_capabilities: frozenset[Capability]
    dominated_groups: tuple[DominatedGroup, ...]
    scheduler: SchedulerPolicy
    shards: tuple[QualityShardSpec, ...]

    @model_validator(mode="after")
    def validate_selection_contract(self) -> QualityFeedbackPlan:
        group_ids = {group.id for group in self.groups}
        if {shard.group_id for shard in self.shards} != group_ids:
            raise ValueError("every selected group requires at least one feedback shard")
        if any(
            shard.plan_hash != self.plan_hash or shard.manifest_hash != self.manifest_hash
            for shard in self.shards
        ):
            raise ValueError("shard identity must match the frozen quality plan")
        return self


class QualityShardResult(FrozenModel):
    schema_version: int = 1
    plan_hash: str
    manifest_hash: str
    group_id: str
    shard_id: str
    root_shard_id: str
    status: FeedbackStatus
    phase: Literal["started", "running", "terminal"] = "terminal"
    update_sequence: int = Field(default=0, ge=0)
    test_ids: tuple[str, ...]
    completed_test_ids: tuple[str, ...]
    remaining_test_ids: tuple[str, ...]
    duration_seconds: float = Field(ge=0, le=300)
    evidence_refs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    exit_code: int | None = None
    output: str = ""

    @model_validator(mode="after")
    def validate_partition(self) -> QualityShardResult:
        completed = set(self.completed_test_ids)
        remaining = set(self.remaining_test_ids)
        expected = set(self.test_ids)
        if completed & remaining or completed | remaining != expected:
            raise ValueError("completed and remaining tests must partition the shard")
        if self.status is FeedbackStatus.PASSED and self.remaining_test_ids:
            raise ValueError("a passed shard cannot retain tests")
        if self.status is FeedbackStatus.IN_PROGRESS and not self.remaining_test_ids:
            raise ValueError("an in-progress shard requires remaining tests")
        return self


class QualityGroupAggregation(FrozenModel):
    group_id: str
    complete: bool
    cache_eligible: bool
    completed_test_ids: tuple[str, ...]
    remaining_test_ids: tuple[str, ...]
    coverage_artifacts: tuple[str, ...]
    result: VerificationResult | None = None


class QualityFeedbackScheduleOutcome(FrozenModel):
    shard_results: tuple[QualityShardResult, ...]
    group_results: tuple[VerificationResult, ...]
    incomplete_groups: tuple[str, ...]
    wall_seconds: float = Field(ge=0)
    critical_path_seconds: float = Field(ge=0)


ShardRunner = Callable[[QualityShardSpec, threading.Event], QualityShardResult]
ShardPublisher = Callable[[QualityShardResult], None]


def _pack_tests(
    test_ids: Sequence[str],
    estimates: Mapping[str, float],
) -> tuple[tuple[tuple[str, float], ...], ...]:
    packed: list[list[tuple[str, float]]] = []
    current: list[tuple[str, float]] = []
    current_seconds = 0.0
    current_characters = 0
    for test_id in test_ids:
        estimate = min(float(estimates.get(test_id, 30.0)), _MAX_ACTION_SECONDS)
        if estimate <= 0:
            raise ValueError(f"test estimate must be positive: {test_id}")
        test_characters = len(test_id) + 1
        if current and (
            current_seconds + estimate >= 240
            or current_characters + test_characters >= _MAX_COMMAND_CHARACTERS
        ):
            packed.append(current)
            current = []
            current_seconds = 0.0
            current_characters = 0
        current.append((test_id, estimate))
        current_seconds += estimate
        current_characters += test_characters
    if current:
        packed.append(current)
    return tuple(tuple(items) for items in packed)


def freeze_quality_feedback_plan(
    plan: VerificationPlan,
    *,
    test_ids_by_group: Mapping[str, Sequence[str]],
    estimated_seconds_by_test: Mapping[str, float],
    estimated_seconds_by_group_test: Mapping[str, Mapping[str, float]] | None = None,
    coverage_groups: frozenset[str] = frozenset(),
) -> QualityFeedbackPlan:
    selected_ids = {group.id for group in plan.groups}
    unknown = set(test_ids_by_group) - selected_ids
    if unknown:
        raise ValueError(f"test IDs supplied for unselected groups: {sorted(unknown)}")
    unknown_coverage = coverage_groups - selected_ids
    if unknown_coverage:
        raise ValueError(
            f"coverage aggregation supplied for unselected groups: {sorted(unknown_coverage)}"
        )

    shards: list[QualityShardSpec] = []
    last_shard_by_group: dict[str, str] = {}
    for group in plan.groups:
        test_ids = tuple(test_ids_by_group.get(group.id, ()))
        if len(set(test_ids)) != len(test_ids):
            raise ValueError(f"test IDs for group {group.id!r} must be unique")
        group_estimates = (
            estimated_seconds_by_group_test.get(group.id, estimated_seconds_by_test)
            if estimated_seconds_by_group_test is not None
            else estimated_seconds_by_test
        )
        batches = _pack_tests(test_ids, group_estimates)
        opaque = not batches
        if not batches:
            synthetic_id = f"group-action:{group.id}"
            batches = (((synthetic_id, _MAX_ACTION_SECONDS),),)
        previous_shard: str | None = None
        for index, raw_batch in enumerate(batches, start=1):
            batch = raw_batch
            shard_id = f"{group.id}-shard-{index}"
            dependency_shards = tuple(
                last_shard_by_group[dependency] for dependency in group.depends_on
            )
            if previous_shard is not None:
                dependency_shards = (previous_shard,)
            batch_ids = tuple(item[0] for item in batch)
            batch_estimates = tuple(item[1] for item in batch)
            shards.append(
                QualityShardSpec(
                    plan_hash=plan.plan_hash,
                    manifest_hash=plan.manifest_hash,
                    group_id=group.id,
                    shard_id=shard_id,
                    root_shard_id=shard_id,
                    sequence=index,
                    opaque=opaque,
                    test_ids=batch_ids,
                    estimated_test_seconds=batch_estimates,
                    estimated_seconds=(
                        min(sum(batch_estimates), _MAX_ACTION_SECONDS)
                        if batch_estimates
                        else _MAX_ACTION_SECONDS
                    ),
                    depends_on=dependency_shards,
                    capabilities=group.capabilities,
                    cacheable=group.cacheable,
                    input_fingerprint=group.input_fingerprint,
                )
            )
            previous_shard = shard_id
        if group.id in coverage_groups:
            assert previous_shard is not None
            coverage_id = f"{group.id}-coverage"
            shards.append(
                QualityShardSpec(
                    plan_hash=plan.plan_hash,
                    manifest_hash=plan.manifest_hash,
                    group_id=group.id,
                    shard_id=coverage_id,
                    root_shard_id=coverage_id,
                    sequence=len(batches) + 1,
                    operation="coverage",
                    opaque=True,
                    test_ids=(f"group-coverage:{group.id}",),
                    estimated_test_seconds=(30.0,),
                    estimated_seconds=30.0,
                    depends_on=(previous_shard,),
                    capabilities=group.capabilities,
                    cacheable=group.cacheable,
                    input_fingerprint=group.input_fingerprint,
                )
            )
            previous_shard = coverage_id
        assert previous_shard is not None
        last_shard_by_group[group.id] = previous_shard

    return QualityFeedbackPlan(
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
        groups=plan.groups,
        required_capabilities=plan.required_capabilities,
        dominated_groups=plan.dominated_groups,
        scheduler=plan.scheduler,
        shards=tuple(shards),
    )


def subdivide_timed_out_shard(
    shard: QualityShardSpec,
    result: QualityShardResult,
) -> tuple[QualityShardSpec, ...]:
    if result.shard_id != shard.shard_id or result.root_shard_id != shard.root_shard_id:
        raise ValueError("timeout result does not belong to the shard")
    if result.status not in {FeedbackStatus.IN_PROGRESS, FeedbackStatus.TIMED_OUT}:
        raise ValueError("only an in-progress or timed-out shard can be subdivided")
    remaining = result.remaining_test_ids
    if not remaining:
        return ()
    estimates = dict(zip(shard.test_ids, shard.estimated_test_seconds, strict=True))
    midpoint = max(1, len(remaining) // 2)
    parts = (remaining[:midpoint], remaining[midpoint:]) if len(remaining) > 1 else (remaining,)
    continuations: list[QualityShardSpec] = []
    previous = shard.shard_id
    next_continuation = shard.continuation_sequence + 1
    for part_index, test_ids in enumerate(parts, start=1):
        if not test_ids:
            continue
        test_estimates = tuple(estimates[test_id] for test_id in test_ids)
        continuation_id = f"{shard.root_shard_id}-continuation-{next_continuation}-{part_index}"
        continuations.append(
            QualityShardSpec(
                **{
                    **shard.model_dump(mode="python"),
                    "shard_id": continuation_id,
                    "continuation_sequence": next_continuation,
                    "test_ids": test_ids,
                    "estimated_test_seconds": test_estimates,
                    "estimated_seconds": min(sum(test_estimates), _MAX_ACTION_SECONDS),
                    "depends_on": (previous,),
                }
            )
        )
        previous = continuation_id
    return tuple(continuations)


def aggregate_quality_group(
    plan: QualityFeedbackPlan,
    group_id: str,
    results: Sequence[QualityShardResult],
) -> QualityGroupAggregation:
    group = next((item for item in plan.groups if item.id == group_id), None)
    if group is None:
        raise KeyError(f"unknown selected group: {group_id}")
    planned_shards = tuple(shard for shard in plan.shards if shard.group_id == group_id)
    expected_ids = tuple(test_id for shard in planned_shards for test_id in shard.test_ids)
    relevant = tuple(result for result in results if result.group_id == group_id)
    for result in relevant:
        if result.plan_hash != plan.plan_hash or result.manifest_hash != plan.manifest_hash:
            raise ValueError("shard result does not belong to the frozen quality plan")

    completed_set = {test_id for result in relevant for test_id in result.completed_test_ids}
    completed = tuple(test_id for test_id in expected_ids if test_id in completed_set)
    remaining = tuple(test_id for test_id in expected_ids if test_id not in completed_set)
    represented_roots = {result.root_shard_id for result in relevant}
    expected_roots = {shard.root_shard_id for shard in planned_shards}
    terminal_empty_shards = {
        result.root_shard_id
        for result in relevant
        if not result.test_ids
        and result.status
        in {FeedbackStatus.PASSED, FeedbackStatus.FAILED, FeedbackStatus.CANCELLED}
    }
    empty_roots = {shard.root_shard_id for shard in planned_shards if not shard.test_ids}
    complete = (
        not remaining
        and represented_roots.issuperset(expected_roots)
        and terminal_empty_shards.issuperset(empty_roots)
    )
    if not complete:
        return QualityGroupAggregation(
            group_id=group_id,
            complete=False,
            cache_eligible=False,
            completed_test_ids=completed,
            remaining_test_ids=remaining,
            coverage_artifacts=(),
        )

    failure_statuses = {
        FeedbackStatus.FAILED,
        FeedbackStatus.TIMED_OUT,
        FeedbackStatus.BLOCKED,
        FeedbackStatus.CANCELLED,
    }
    failed = any(result.status in failure_statuses for result in relevant)
    artifacts = tuple(
        artifact
        for artifact in group.artifacts
        if any(artifact in result.artifacts for result in relevant)
    )
    duration = sum(result.duration_seconds for result in relevant)
    verification = VerificationResult(
        group_id=group.id,
        required=group.required,
        status=ResultStatus.FAILED if failed else ResultStatus.PASSED,
        exit_code=1 if failed else 0,
        duration_seconds=duration,
        run_seconds=duration,
        failure_kind="feedback-shard" if failed else None,
        artifacts=artifacts,
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
        input_fingerprint=group.input_fingerprint,
        output="\n".join(result.output for result in relevant if result.output),
    )
    cache_eligible = (
        group.cacheable
        and verification.status is ResultStatus.PASSED
        and set(artifacts) == set(group.artifacts)
    )
    return QualityGroupAggregation(
        group_id=group_id,
        complete=True,
        cache_eligible=cache_eligible,
        completed_test_ids=completed,
        remaining_test_ids=(),
        coverage_artifacts=artifacts,
        result=verification,
    )


def run_feedback_schedule(
    plan: QualityFeedbackPlan,
    run: ShardRunner,
    *,
    publish: ShardPublisher,
    cancellation_event: threading.Event | None = None,
    prior_results: Sequence[QualityShardResult] = (),
) -> QualityFeedbackScheduleOutcome:
    source_by_id = {group.id: group for group in plan.groups}
    shard_by_id = {shard.shard_id: shard for shard in plan.shards}
    scheduled = tuple(
        PlannedGroup.model_validate(
            {
                **source_by_id[shard.group_id].model_dump(mode="python"),
                "id": shard.shard_id,
                "depends_on": shard.depends_on,
                "cacheable": False,
            }
        )
        for shard in plan.shards
    )
    recorded: dict[str, QualityShardResult] = {}
    lock = threading.Lock()
    prior_by_id = {result.shard_id: result for result in prior_results}

    def execute(group: PlannedGroup, event: threading.Event) -> VerificationResult:
        shard = shard_by_id[group.id]
        prior = prior_by_id.get(shard.shard_id)
        if (
            prior is not None
            and prior.status is FeedbackStatus.PASSED
            and prior.phase == "terminal"
            and prior.plan_hash == plan.plan_hash
            and prior.manifest_hash == plan.manifest_hash
            and prior.group_id == shard.group_id
            and prior.root_shard_id == shard.root_shard_id
            and prior.test_ids == shard.test_ids
        ):
            result = prior
        else:
            result = run(shard, event)
        if (
            result.shard_id != shard.shard_id
            or result.group_id != shard.group_id
            or result.plan_hash != plan.plan_hash
            or result.manifest_hash != plan.manifest_hash
        ):
            raise ValueError("runner returned a result for a different shard")
        with lock:
            recorded[shard.shard_id] = result
        publish(result)
        status_by_feedback = {
            FeedbackStatus.PASSED: ResultStatus.PASSED,
            FeedbackStatus.FAILED: ResultStatus.FAILED,
            FeedbackStatus.TIMED_OUT: ResultStatus.FAILED,
            FeedbackStatus.CANCELLED: ResultStatus.CANCELLED,
            FeedbackStatus.BLOCKED: ResultStatus.BLOCKED,
            FeedbackStatus.IN_PROGRESS: ResultStatus.BLOCKED,
        }
        status = status_by_feedback[result.status]
        return VerificationResult(
            group_id=shard.shard_id,
            required=True,
            status=status,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            failure_kind=None if status is ResultStatus.PASSED else "feedback-shard",
            plan_hash=plan.plan_hash,
            manifest_hash=plan.manifest_hash,
            output=result.output,
        )

    schedule = run_schedule(
        scheduled,
        plan.scheduler,
        execute,
        cancellation_event=cancellation_event,
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
    )
    for shard, scheduled_result in zip(plan.shards, schedule.results, strict=True):
        if shard.shard_id in recorded:
            continue
        status = {
            ResultStatus.FAILED: FeedbackStatus.FAILED,
            ResultStatus.CANCELLED: FeedbackStatus.CANCELLED,
        }.get(scheduled_result.status, FeedbackStatus.BLOCKED)
        synthesized = QualityShardResult(
            plan_hash=plan.plan_hash,
            manifest_hash=plan.manifest_hash,
            group_id=shard.group_id,
            shard_id=shard.shard_id,
            root_shard_id=shard.root_shard_id,
            status=status,
            test_ids=shard.test_ids,
            completed_test_ids=(),
            remaining_test_ids=shard.test_ids,
            duration_seconds=scheduled_result.duration_seconds,
            output=scheduled_result.output or scheduled_result.remediation,
        )
        recorded[shard.shard_id] = synthesized
        publish(synthesized)

    shard_results = tuple(recorded[shard.shard_id] for shard in plan.shards)
    aggregations = tuple(
        aggregate_quality_group(plan, group.id, shard_results) for group in plan.groups
    )
    return QualityFeedbackScheduleOutcome(
        shard_results=shard_results,
        group_results=tuple(
            aggregation.result for aggregation in aggregations if aggregation.result is not None
        ),
        incomplete_groups=tuple(
            aggregation.group_id for aggregation in aggregations if not aggregation.complete
        ),
        wall_seconds=schedule.wall_seconds,
        critical_path_seconds=schedule.critical_path_seconds,
    )
