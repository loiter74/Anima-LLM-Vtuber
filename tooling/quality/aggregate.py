from __future__ import annotations

from collections.abc import Iterable

from .models import (
    AggregateStatus,
    AggregateSummary,
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

    required_problem = any(
        group_id in required_ids
        for group_id in (*failed, *blocked, *cancelled)
    )
    if missing_required or unexpected or required_problem:
        status = AggregateStatus.FAILED
    elif optional_problem:
        status = AggregateStatus.DEGRADED
    else:
        status = AggregateStatus.PASSED

    return AggregateSummary(
        status=status,
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
        missing_groups=tuple(missing),
        failed_groups=tuple(sorted(failed)),
        blocked_groups=tuple(sorted(blocked)),
        cancelled_groups=tuple(sorted(cancelled)),
        unexpected_groups=tuple(unexpected),
    )
