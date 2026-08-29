from __future__ import annotations

import threading

from tooling.execution_feedback import FeedbackStatus
from tooling.quality.feedback import (
    QualityShardResult,
    aggregate_quality_group,
    freeze_quality_feedback_plan,
    run_feedback_schedule,
    subdivide_timed_out_shard,
)
from tooling.quality.models import (
    Capability,
    Domain,
    DominatedGroup,
    Isolation,
    PlannedGroup,
    ResourceClass,
    ResultStatus,
    Runner,
    SchedulerPolicy,
    Tier,
    VerificationKind,
    VerificationPlan,
)


def _group(
    group_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    capabilities: frozenset[Capability] = frozenset(),
    cacheable: bool = True,
) -> PlannedGroup:
    return PlannedGroup(
        id=group_id,
        domain=Domain.REPOSITORY,
        kind=VerificationKind.UNIT,
        runner=Runner.PYTEST,
        isolation=Isolation.HERMETIC,
        capabilities=capabilities,
        depends_on=depends_on,
        artifacts=(f"artifacts/{group_id}.xml",),
        required=True,
        reasons=("machine-selected",),
        cacheable=cacheable,
        resource_class=ResourceClass.CPU,
        resource_weight=2,
        input_fingerprint=("a" if group_id == "collect" else "b") * 64,
        input_patterns=(f"tests/{group_id}/**",),
        toolchain_identity={"python": "3.13"},
    )


def _plan() -> VerificationPlan:
    groups = (
        _group("collect"),
        _group(
            "verify",
            depends_on=("collect",),
            capabilities=frozenset({Capability.DOCKER}),
            cacheable=False,
        ),
    )
    return VerificationPlan(
        tier=Tier.AFFECTED,
        source="paths",
        changes=(),
        groups=groups,
        required_capabilities=frozenset({Capability.DOCKER}),
        dominated_groups=(
            DominatedGroup(
                id="focused",
                covering_group="verify",
                reasons=("coverage dominance",),
            ),
        ),
        scheduler=SchedulerPolicy(max_workers=2, max_weight=4),
        manifest_hash="manifest",
        plan_hash="plan",
    )


def _result(
    shard,
    *,
    status: FeedbackStatus = FeedbackStatus.PASSED,
    completed: tuple[str, ...] | None = None,
    remaining: tuple[str, ...] = (),
) -> QualityShardResult:
    return QualityShardResult(
        plan_hash="plan",
        manifest_hash="manifest",
        group_id=shard.group_id,
        shard_id=shard.shard_id,
        root_shard_id=shard.root_shard_id,
        status=status,
        test_ids=shard.test_ids,
        completed_test_ids=shard.test_ids if completed is None else completed,
        remaining_test_ids=remaining,
        duration_seconds=120,
        evidence_refs=(f"evidence:{shard.shard_id}",),
        artifacts=(f"artifacts/{shard.group_id}.xml",),
        exit_code=0 if status is FeedbackStatus.PASSED else None,
    )


def test_freeze_preserves_machine_selection_contract_and_shards_under_240_seconds() -> None:
    source = _plan()
    feedback = freeze_quality_feedback_plan(
        source,
        test_ids_by_group={
            "collect": ("test_a", "test_b", "test_c"),
            "verify": ("test_d",),
        },
        estimated_seconds_by_test={
            "test_a": 120,
            "test_b": 100,
            "test_c": 80,
            "test_d": 400,
        },
    )

    assert feedback.groups == source.groups
    assert feedback.required_capabilities == source.required_capabilities
    assert feedback.dominated_groups == source.dominated_groups
    assert feedback.scheduler == source.scheduler
    assert all(shard.estimated_seconds < 240 for shard in feedback.shards)
    assert tuple(test_id for shard in feedback.shards for test_id in shard.test_ids) == (
        "test_a",
        "test_b",
        "test_c",
        "test_d",
    )
    verify_first = next(shard for shard in feedback.shards if shard.group_id == "verify")
    collect_last = tuple(shard for shard in feedback.shards if shard.group_id == "collect")[-1]
    assert verify_first.depends_on == (collect_last.shard_id,)
    assert verify_first.capabilities == frozenset({Capability.DOCKER})
    assert verify_first.cacheable is False


def test_timeout_subdivision_uses_only_reported_remaining_tests() -> None:
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": ("test_a", "test_b", "test_c"), "verify": ("test_d",)},
        estimated_seconds_by_test={
            test_id: 60 for test_id in ("test_a", "test_b", "test_c", "test_d")
        },
    )
    shard = next(shard for shard in feedback.shards if shard.group_id == "collect")
    timed_out = _result(
        shard,
        status=FeedbackStatus.IN_PROGRESS,
        completed=("test_a",),
        remaining=("test_b", "test_c"),
    )

    continuations = subdivide_timed_out_shard(shard, timed_out)

    assert tuple(test_id for item in continuations for test_id in item.test_ids) == (
        "test_b",
        "test_c",
    )
    assert all(item.root_shard_id == shard.root_shard_id for item in continuations)
    partial = aggregate_quality_group(feedback, "collect", (timed_out,))
    resumed = aggregate_quality_group(
        feedback,
        "collect",
        (timed_out, *(_result(continuation) for continuation in continuations)),
    )
    expired = timed_out.model_copy(update={"status": FeedbackStatus.TIMED_OUT})
    expired_partial = aggregate_quality_group(feedback, "collect", (expired,))
    expired_resumed = aggregate_quality_group(
        feedback,
        "collect",
        (expired, *(_result(continuation) for continuation in continuations)),
    )
    assert partial.complete is False
    assert partial.cache_eligible is False
    assert partial.result is not None
    assert partial.result.status is ResultStatus.BLOCKED
    assert resumed.complete is True
    assert resumed.result is not None
    assert resumed.result.status is ResultStatus.PASSED
    assert expired_partial.result is not None
    assert expired_partial.result.status is ResultStatus.FAILED
    assert expired_resumed.result is not None
    assert expired_resumed.result.status is ResultStatus.PASSED


def test_sharding_also_bounds_generated_command_line_size() -> None:
    long_ids = tuple(f"test_{index}_" + ("x" * 12_000) for index in range(3))
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": long_ids, "verify": ("test_d",)},
        estimated_seconds_by_test={test_id: 1 for test_id in (*long_ids, "test_d")},
    )

    collect = tuple(shard for shard in feedback.shards if shard.group_id == "collect")

    assert len(collect) == 3
    assert all(sum(len(test_id) + 1 for test_id in shard.test_ids) < 24_000 for shard in collect)


def test_group_result_and_artifacts_exist_only_after_every_required_shard_completes() -> None:
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": ("test_a", "test_b", "test_c"), "verify": ("test_d",)},
        estimated_seconds_by_test={"test_a": 120, "test_b": 100, "test_c": 80, "test_d": 60},
    )
    collect = tuple(shard for shard in feedback.shards if shard.group_id == "collect")

    partial = aggregate_quality_group(feedback, "collect", (_result(collect[0]),))
    complete = aggregate_quality_group(
        feedback,
        "collect",
        tuple(_result(shard) for shard in collect),
    )

    assert partial.result is None
    assert partial.coverage_artifacts == ()
    assert complete.complete is True
    assert complete.cache_eligible is True
    assert complete.result is not None
    assert complete.result.artifacts == ("artifacts/collect.xml",)


def test_coverage_group_adds_one_terminal_aggregation_shard() -> None:
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": ("test_a", "test_b"), "verify": ("test_d",)},
        estimated_seconds_by_test={"test_a": 120, "test_b": 120, "test_d": 60},
        coverage_groups=frozenset({"collect"}),
    )

    collect = tuple(shard for shard in feedback.shards if shard.group_id == "collect")

    assert [shard.operation for shard in collect] == ["test", "test", "coverage"]
    assert collect[-1].test_ids == ("group-coverage:collect",)
    assert collect[-1].depends_on == (collect[-2].shard_id,)

    partial = aggregate_quality_group(
        feedback,
        "collect",
        tuple(_result(shard) for shard in collect[:-1]),
    )
    complete = aggregate_quality_group(
        feedback,
        "collect",
        tuple(_result(shard) for shard in collect),
    )

    assert partial.complete is False
    assert partial.coverage_artifacts == ()
    assert complete.complete is True


def test_feedback_scheduler_keeps_group_dependencies_and_publishes_each_shard() -> None:
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": ("test_a", "test_b"), "verify": ("test_d",)},
        estimated_seconds_by_test={"test_a": 120, "test_b": 120, "test_d": 60},
    )
    published: list[str] = []
    execution_order: list[str] = []
    lock = threading.Lock()

    def run(shard, _event):
        with lock:
            execution_order.append(shard.shard_id)
        return _result(shard)

    outcome = run_feedback_schedule(
        feedback,
        run,
        publish=lambda result: published.append(result.shard_id),
    )

    collect_ids = [shard.shard_id for shard in feedback.shards if shard.group_id == "collect"]
    verify_id = next(shard.shard_id for shard in feedback.shards if shard.group_id == "verify")
    assert execution_order.index(verify_id) > max(
        execution_order.index(item) for item in collect_ids
    )
    assert set(published) == {shard.shard_id for shard in feedback.shards}
    assert tuple(result.group_id for result in outcome.group_results) == ("collect", "verify")
    assert outcome.incomplete_groups == ()


def test_feedback_scheduler_reuses_matching_passed_shards() -> None:
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": ("test_a", "test_b"), "verify": ("test_d",)},
        estimated_seconds_by_test={"test_a": 120, "test_b": 120, "test_d": 60},
    )
    first = feedback.shards[0]
    prior = _result(first)
    executed: list[str] = []

    def run(shard, _event):
        executed.append(shard.shard_id)
        return _result(shard)

    outcome = run_feedback_schedule(
        feedback,
        run,
        publish=lambda _result: None,
        prior_results=(prior,),
    )

    assert first.shard_id not in executed
    assert outcome.incomplete_groups == ()


def test_feedback_scheduler_publishes_terminal_evidence_for_dependency_blocked_shards() -> None:
    feedback = freeze_quality_feedback_plan(
        _plan(),
        test_ids_by_group={"collect": ("test_a", "test_b"), "verify": ("test_d",)},
        estimated_seconds_by_test={"test_a": 120, "test_b": 120, "test_d": 60},
    )
    first = feedback.shards[0]
    published: list[QualityShardResult] = []

    def run(shard, _event):
        if shard.shard_id == first.shard_id:
            return _result(
                shard,
                status=FeedbackStatus.FAILED,
                completed=shard.test_ids,
            )
        return _result(shard)

    outcome = run_feedback_schedule(feedback, run, publish=published.append)

    assert {result.shard_id for result in published} == {
        shard.shard_id for shard in feedback.shards
    }
    blocked = tuple(result for result in published if result.shard_id != first.shard_id)
    assert blocked
    assert all(result.phase == "terminal" for result in blocked)
    assert all(
        result.status in {FeedbackStatus.BLOCKED, FeedbackStatus.CANCELLED} for result in blocked
    )
    assert tuple(result.group_id for result in outcome.group_results) == ("collect", "verify")
    assert all(result.status is not ResultStatus.PASSED for result in outcome.group_results)
    assert all(result.artifacts == () for result in outcome.group_results)
    assert outcome.incomplete_groups == ("collect", "verify")
