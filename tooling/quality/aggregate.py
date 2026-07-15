from __future__ import annotations

from collections.abc import Iterable

from .models import (
    AggregateStatus,
    AggregateSummary,
    ExecutionMode,
    ResultStatus,
    VerificationPlan,
    VerificationResult,
)


def aggregate_results(
    plan: VerificationPlan,
    results: Iterable[VerificationResult],
) -> AggregateSummary:
    planned = {group.id: group for group in plan.groups}
    provided = {result.group_id: result for result in results}
    required_ids = {group_id for group_id, group in planned.items() if group.required}

    missing_required = required_ids - provided.keys()
    missing = sorted(planned.keys() - provided.keys())
    unexpected = sorted(provided.keys() - planned.keys())
    failed: list[str] = []
    blocked: list[str] = []
    cancelled: list[str] = []
    optional_problem = any(group_id not in required_ids for group_id in missing)

    for group_id, result in provided.items():
        if group_id not in planned:
            continue
        if result.plan_hash != plan.plan_hash or result.manifest_hash != plan.manifest_hash:
            failed.append(group_id)
            continue
        if result.status is ResultStatus.FAILED:
            failed.append(group_id)
        elif result.status is ResultStatus.BLOCKED:
            blocked.append(group_id)
        elif result.status is ResultStatus.CANCELLED:
            cancelled.append(group_id)
        elif result.status is ResultStatus.SKIPPED and group_id in required_ids:
            blocked.append(group_id)
        if not planned[group_id].required and result.status is not ResultStatus.PASSED:
            optional_problem = True

    required_problem = any(group_id in required_ids for group_id in (*failed, *blocked, *cancelled))
    if missing_required or unexpected or required_problem:
        status = AggregateStatus.FAILED
    elif optional_problem:
        status = AggregateStatus.DEGRADED
    else:
        status = AggregateStatus.PASSED

    cache_hits = tuple(
        group_id
        for group_id in planned
        if group_id in provided and provided[group_id].execution_mode is ExecutionMode.CACHE_HIT
    )
    executed = tuple(
        group_id
        for group_id in planned
        if group_id in provided and provided[group_id].execution_mode is ExecutionMode.EXECUTED
    )
    cacheable_provided = tuple(
        group_id for group_id, group in planned.items() if group.cacheable and group_id in provided
    )
    cache_misses = tuple(group_id for group_id in cacheable_provided if group_id not in cache_hits)
    cache_hit_ratio = len(cache_hits) / len(cacheable_provided) if cacheable_provided else 0

    return AggregateSummary(
        status=status,
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
        missing_groups=tuple(missing),
        failed_groups=tuple(sorted(failed)),
        blocked_groups=tuple(sorted(blocked)),
        cancelled_groups=tuple(sorted(cancelled)),
        unexpected_groups=tuple(unexpected),
        dominated_groups=plan.dominated_groups,
        docker_actions=plan.docker_actions,
        cache_hit_groups=cache_hits,
        executed_groups=executed,
        cache_miss_groups=cache_misses,
        queue_seconds=sum(result.queue_seconds for result in provided.values()),
        run_seconds=sum(result.run_seconds for result in provided.values()),
        cache_seconds=sum(result.cache_seconds for result in provided.values()),
        cache_hit_ratio=cache_hit_ratio,
    )
