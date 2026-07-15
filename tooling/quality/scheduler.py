from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from pydantic import Field

from .models import (
    ExecutionMode,
    FrozenModel,
    PlannedGroup,
    ResourceClass,
    ResultStatus,
    SchedulerPolicy,
    VerificationResult,
)

GroupRunner = Callable[[PlannedGroup, threading.Event], VerificationResult]


class ScheduleOutcome(FrozenModel):
    results: tuple[VerificationResult, ...]
    wall_seconds: float = Field(ge=0)
    critical_path_seconds: float = Field(ge=0)
    peak_weight: int = Field(ge=0)
    peak_heavy: int = Field(ge=0)
    peak_exclusive: int = Field(ge=0)


def _synthetic_result(
    group: PlannedGroup,
    *,
    status: ResultStatus,
    failure_kind: str,
    remediation: str,
    plan_hash: str,
    manifest_hash: str,
    queue_seconds: float,
) -> VerificationResult:
    return VerificationResult(
        group_id=group.id,
        required=group.required,
        status=status,
        exit_code=None,
        duration_seconds=0,
        failure_kind=failure_kind,
        plan_hash=plan_hash,
        manifest_hash=manifest_hash,
        input_fingerprint=group.input_fingerprint,
        queue_seconds=queue_seconds,
        remediation=remediation,
    )


def _critical_path(
    groups: Sequence[PlannedGroup],
    results: dict[str, VerificationResult],
) -> float:
    elapsed_by_group: dict[str, float] = {}
    for group in groups:
        result = results[group.id]
        own_duration = result.run_seconds + result.cache_seconds
        if own_duration == 0:
            own_duration = result.duration_seconds
        dependency_duration = max(
            (elapsed_by_group[dependency] for dependency in group.depends_on),
            default=0,
        )
        elapsed_by_group[group.id] = dependency_duration + own_duration
    return max(elapsed_by_group.values(), default=0)


def run_schedule(
    groups: Sequence[PlannedGroup],
    policy: SchedulerPolicy,
    run: GroupRunner,
    *,
    cancellation_event: threading.Event | None = None,
    plan_hash: str = "",
    manifest_hash: str = "",
) -> ScheduleOutcome:
    cancellation = cancellation_event or threading.Event()
    ordered_groups = tuple(groups)
    group_by_id = {group.id: group for group in ordered_groups}
    if len(group_by_id) != len(ordered_groups):
        raise ValueError("scheduled group IDs must be unique")
    for group in ordered_groups:
        unknown = set(group.depends_on) - set(group_by_id)
        if unknown:
            raise ValueError(f"group {group.id!r} has unscheduled dependencies: {sorted(unknown)}")

    schedule_started = time.perf_counter()
    pending = [group.id for group in ordered_groups]
    results: dict[str, VerificationResult] = {}
    running: dict[Future[VerificationResult], tuple[PlannedGroup, float]] = {}
    current_weight = 0
    current_heavy = 0
    current_exclusive = 0
    peak_weight = 0
    peak_heavy = 0
    peak_exclusive = 0

    def can_start(group: PlannedGroup) -> bool:
        if len(running) >= policy.max_workers:
            return False
        if current_weight + group.resource_weight > policy.max_weight:
            return False
        if current_exclusive:
            return False
        if group.resource_class is ResourceClass.EXCLUSIVE:
            return not running and current_exclusive < policy.max_exclusive
        return not (
            group.resource_class is ResourceClass.HEAVY and current_heavy >= policy.max_heavy
        )

    with ThreadPoolExecutor(
        max_workers=policy.max_workers,
        thread_name_prefix="quality",
    ) as pool:
        while pending or running:
            now = time.perf_counter()
            queue_seconds = now - schedule_started
            made_progress = False

            if cancellation.is_set():
                for group_id in pending:
                    group = group_by_id[group_id]
                    results[group_id] = _synthetic_result(
                        group,
                        status=ResultStatus.CANCELLED,
                        failure_kind="cancelled",
                        remediation="Cancelled before execution",
                        plan_hash=plan_hash,
                        manifest_hash=manifest_hash,
                        queue_seconds=queue_seconds,
                    )
                pending.clear()
                made_progress = True
            else:
                for group_id in tuple(pending):
                    group = group_by_id[group_id]
                    completed_dependencies = [
                        results[dependency]
                        for dependency in group.depends_on
                        if dependency in results
                    ]
                    failed_dependencies = [
                        result.group_id
                        for result in completed_dependencies
                        if result.status is not ResultStatus.PASSED
                    ]
                    if failed_dependencies:
                        results[group_id] = _synthetic_result(
                            group,
                            status=ResultStatus.BLOCKED,
                            failure_kind="dependency",
                            remediation=(
                                "Blocked by unsuccessful dependencies: "
                                + ", ".join(sorted(failed_dependencies))
                            ),
                            plan_hash=plan_hash,
                            manifest_hash=manifest_hash,
                            queue_seconds=queue_seconds,
                        )
                        pending.remove(group_id)
                        made_progress = True
                        continue
                    if any(dependency not in results for dependency in group.depends_on):
                        continue
                    if not can_start(group):
                        continue
                    submitted_at = time.perf_counter()
                    future = pool.submit(run, group, cancellation)
                    running[future] = (group, submitted_at)
                    pending.remove(group_id)
                    current_weight += group.resource_weight
                    if group.resource_class is ResourceClass.HEAVY:
                        current_heavy += 1
                    if group.resource_class is ResourceClass.EXCLUSIVE:
                        current_exclusive += 1
                    peak_weight = max(peak_weight, current_weight)
                    peak_heavy = max(peak_heavy, current_heavy)
                    peak_exclusive = max(peak_exclusive, current_exclusive)
                    made_progress = True

            if running:
                try:
                    completed, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                except KeyboardInterrupt:
                    cancellation.set()
                    continue
                for future in completed:
                    group, submitted_at = running.pop(future)
                    current_weight -= group.resource_weight
                    if group.resource_class is ResourceClass.HEAVY:
                        current_heavy -= 1
                    if group.resource_class is ResourceClass.EXCLUSIVE:
                        current_exclusive -= 1
                    elapsed = time.perf_counter() - submitted_at
                    try:
                        result = future.result()
                    except Exception as exc:  # noqa: BLE001 - converted to evidence
                        result = _synthetic_result(
                            group,
                            status=ResultStatus.FAILED,
                            failure_kind="scheduler-runner",
                            remediation=f"Runner raised {type(exc).__name__}: {exc}",
                            plan_hash=plan_hash,
                            manifest_hash=manifest_hash,
                            queue_seconds=submitted_at - schedule_started,
                        )
                    updates: dict[str, object] = {
                        "queue_seconds": submitted_at - schedule_started,
                        "input_fingerprint": group.input_fingerprint,
                    }
                    if result.duration_seconds == 0:
                        updates["duration_seconds"] = elapsed
                    if result.execution_mode is ExecutionMode.EXECUTED and result.run_seconds == 0:
                        updates["run_seconds"] = elapsed
                    results[group.id] = result.model_copy(update=updates)
                made_progress = True

            if pending and not running and not made_progress:
                raise RuntimeError(
                    "scheduler made no progress; dependency graph or resource policy is invalid"
                )

    wall_seconds = time.perf_counter() - schedule_started
    ordered_results = tuple(results[group.id] for group in ordered_groups)
    return ScheduleOutcome(
        results=ordered_results,
        wall_seconds=wall_seconds,
        critical_path_seconds=_critical_path(ordered_groups, results),
        peak_weight=peak_weight,
        peak_heavy=peak_heavy,
        peak_exclusive=peak_exclusive,
    )
