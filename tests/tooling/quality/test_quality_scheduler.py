from __future__ import annotations

import threading
import time

from tooling.quality.models import (
    Domain,
    Isolation,
    PlannedGroup,
    ResourceClass,
    ResultStatus,
    Runner,
    SchedulerPolicy,
    VerificationKind,
    VerificationResult,
)
from tooling.quality.scheduler import run_schedule


def _group(
    group_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    resource_class: ResourceClass = ResourceClass.CPU,
    weight: int = 1,
) -> PlannedGroup:
    return PlannedGroup(
        id=group_id,
        domain=Domain.REPOSITORY,
        kind=VerificationKind.UNIT,
        runner=Runner.PYTEST,
        isolation=Isolation.HERMETIC,
        capabilities=frozenset(),
        depends_on=depends_on,
        artifacts=(),
        required=True,
        reasons=("test",),
        resource_class=resource_class,
        resource_weight=weight,
    )


def _result(group: PlannedGroup, status: ResultStatus = ResultStatus.PASSED) -> VerificationResult:
    return VerificationResult(
        group_id=group.id,
        required=group.required,
        status=status,
        exit_code=0 if status is ResultStatus.PASSED else 1,
        duration_seconds=0,
        plan_hash="plan",
        manifest_hash="manifest",
    )


def _policy(
    *,
    workers: int = 4,
    weight: int = 4,
    heavy: int = 1,
    exclusive: int = 1,
) -> SchedulerPolicy:
    return SchedulerPolicy(
        max_workers=workers,
        max_weight=weight,
        max_heavy=heavy,
        max_exclusive=exclusive,
    )


def test_independent_groups_overlap_and_results_keep_plan_order() -> None:
    groups = (_group("slow"), _group("fast"))
    intervals: dict[str, tuple[float, float]] = {}

    def run(group: PlannedGroup, _: threading.Event) -> VerificationResult:
        started = time.perf_counter()
        time.sleep(0.08 if group.id == "slow" else 0.02)
        intervals[group.id] = (started, time.perf_counter())
        return _result(group)

    started = time.perf_counter()
    outcome = run_schedule(groups, _policy(workers=2, weight=2), run)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.14
    assert intervals["slow"][0] < intervals["fast"][1]
    assert intervals["fast"][0] < intervals["slow"][1]
    assert [result.group_id for result in outcome.results] == ["slow", "fast"]


def test_dependency_runs_only_after_successful_prerequisite() -> None:
    groups = (_group("first"), _group("second", depends_on=("first",)))
    timestamps: dict[str, tuple[float, float]] = {}

    def run(group: PlannedGroup, _: threading.Event) -> VerificationResult:
        started = time.perf_counter()
        time.sleep(0.02)
        timestamps[group.id] = (started, time.perf_counter())
        return _result(group)

    outcome = run_schedule(groups, _policy(workers=2), run)

    assert timestamps["second"][0] >= timestamps["first"][1]
    assert all(result.status is ResultStatus.PASSED for result in outcome.results)


def test_weight_and_heavy_limits_are_never_exceeded() -> None:
    groups = tuple(
        _group(
            f"heavy-{index}",
            resource_class=ResourceClass.HEAVY,
            weight=2,
        )
        for index in range(3)
    )
    active = 0
    peak = 0
    lock = threading.Lock()

    def run(group: PlannedGroup, _: threading.Event) -> VerificationResult:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.025)
        with lock:
            active -= 1
        return _result(group)

    outcome = run_schedule(
        groups,
        _policy(workers=3, weight=4, heavy=1),
        run,
    )

    assert peak == 1
    assert outcome.peak_weight == 2
    assert outcome.peak_heavy == 1


def test_exclusive_group_never_overlaps_other_work() -> None:
    groups = (
        _group("normal"),
        _group("exclusive", resource_class=ResourceClass.EXCLUSIVE, weight=4),
    )
    active: set[str] = set()
    overlaps: list[set[str]] = []
    lock = threading.Lock()

    def run(group: PlannedGroup, _: threading.Event) -> VerificationResult:
        with lock:
            active.add(group.id)
            overlaps.append(set(active))
        time.sleep(0.02)
        with lock:
            active.remove(group.id)
        return _result(group)

    outcome = run_schedule(groups, _policy(workers=2, weight=4), run)

    assert not any(len(snapshot) > 1 for snapshot in overlaps)
    assert outcome.peak_exclusive == 1


def test_failed_dependency_blocks_dependent_without_running_it() -> None:
    groups = (_group("failing"), _group("dependent", depends_on=("failing",)))
    called: list[str] = []

    def run(group: PlannedGroup, _: threading.Event) -> VerificationResult:
        called.append(group.id)
        return _result(
            group,
            ResultStatus.FAILED if group.id == "failing" else ResultStatus.PASSED,
        )

    outcome = run_schedule(groups, _policy(), run)
    by_id = {result.group_id: result for result in outcome.results}

    assert called == ["failing"]
    assert by_id["dependent"].status is ResultStatus.BLOCKED
    assert by_id["dependent"].failure_kind == "dependency"


def test_interrupt_cancels_pending_groups_deterministically() -> None:
    cancellation = threading.Event()
    groups = (_group("running"), _group("pending", depends_on=("running",)))

    def run(group: PlannedGroup, event: threading.Event) -> VerificationResult:
        event.set()
        time.sleep(0.01)
        return _result(group)

    outcome = run_schedule(
        groups,
        _policy(workers=2),
        run,
        cancellation_event=cancellation,
    )
    by_id = {result.group_id: result for result in outcome.results}

    assert by_id["running"].status is ResultStatus.PASSED
    assert by_id["pending"].status is ResultStatus.CANCELLED
    assert by_id["pending"].failure_kind == "cancelled"


def test_runner_exception_is_a_structured_failure() -> None:
    group = _group("boom")

    def run(_: PlannedGroup, __: threading.Event) -> VerificationResult:
        raise RuntimeError("controlled failure")

    outcome = run_schedule((group,), _policy(), run)

    assert outcome.results[0].status is ResultStatus.FAILED
    assert outcome.results[0].failure_kind == "scheduler-runner"
    assert "controlled failure" in outcome.results[0].remediation
