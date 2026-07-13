from __future__ import annotations

import fnmatch
import hashlib
import json
from collections import deque

from .manifest import LoadedCatalog
from .models import (
    Capability,
    Change,
    ChangeSet,
    Domain,
    PlannedGroup,
    Risk,
    Tier,
    VerificationPlan,
)


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def matching_components(loaded: LoadedCatalog, path: str) -> tuple[str, ...]:
    normalized = path.replace("\\", "/")
    return tuple(
        sorted(
            component_id
            for component_id, component in loaded.catalog.components.items()
            if any(_matches(normalized, pattern) for pattern in component.paths)
        )
    )


def _change_paths(change: Change) -> tuple[str, ...]:
    return (change.path,) if not change.old_path else (change.path, change.old_path)


def _infer_domain(path: str) -> Domain:
    if path.startswith("src/animetta/") or path.startswith("tests/"):
        return Domain.BACKEND
    if path.startswith("frontend/"):
        return Domain.FRONTEND
    return Domain.REPOSITORY


def _plan_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verification_plan_hash(plan: VerificationPlan) -> str:
    payload = {
        "schema_version": plan.schema_version,
        "tier": plan.tier.value,
        "source": plan.source,
        "base_sha": plan.base_sha,
        "head_sha": plan.head_sha,
        "changes": [change.model_dump(mode="json") for change in plan.changes],
        "groups": [group.model_dump(mode="json") for group in plan.groups],
        "required_capabilities": sorted(
            capability.value for capability in plan.required_capabilities
        ),
        "fallbacks": sorted(plan.fallbacks),
        "manifest_hash": plan.manifest_hash,
    }
    return _plan_hash(payload)


def plan_verification(
    loaded: LoadedCatalog,
    change_set: ChangeSet,
    tier: Tier | str,
    *,
    discovery_failure: str | None = None,
) -> VerificationPlan:
    selected_tier = Tier(tier)
    catalog = loaded.catalog
    reasons: dict[str, set[str]] = {}
    fallbacks: list[str] = []

    def add_group(group_id: str, reason: str) -> None:
        reasons.setdefault(group_id, set()).add(reason)
        for dependency_id in catalog.groups[group_id].depends_on:
            add_group(dependency_id, f"execution dependency of {group_id}")

    def add_fallback(domain: Domain, reason: str) -> None:
        fallbacks.append(reason)
        for group_id in catalog.fallbacks.for_domain(domain):
            add_group(group_id, reason)

    def add_full_policy() -> None:
        for group_id, group in catalog.groups.items():
            if group.include_in_full and group.isolation.value == "hermetic":
                add_group(group_id, f"selected by {selected_tier.value} policy")
            if selected_tier is Tier.NIGHTLY and group.include_in_nightly:
                add_group(group_id, "selected by nightly service policy")

    if selected_tier in {Tier.QUICK, Tier.AFFECTED}:
        for group_id in catalog.quick_groups:
            add_group(group_id, "required quick policy")

    if discovery_failure:
        reason = f"discovery failure: {discovery_failure}"
        if selected_tier in {Tier.FULL, Tier.NIGHTLY}:
            fallbacks.append(reason)
            add_full_policy()
        else:
            add_fallback(Domain.REPOSITORY, reason)
    elif selected_tier in {Tier.FULL, Tier.NIGHTLY}:
        add_full_policy()
    else:
        seed_components: set[str] = set()
        for change in change_set.changes:
            matched_for_change: set[str] = set()
            for path in _change_paths(change):
                matched_for_path: set[str] = set()
                for component_id, component in catalog.components.items():
                    if any(_matches(path, pattern) for pattern in component.paths):
                        matched_for_path.add(component_id)
                if not matched_for_path:
                    domain = _infer_domain(path)
                    add_fallback(domain, f"unknown {domain.value} path: {path}")
                matched_for_change.update(matched_for_path)
            seed_components.update(matched_for_change)

        selected_components: set[str] = set(seed_components)
        impact_reason: dict[str, str] = {}
        if selected_tier is Tier.AFFECTED:
            queue = deque(sorted(seed_components))
            while queue:
                component_id = queue.popleft()
                for impacted_id in catalog.components[component_id].impacts:
                    if impacted_id in selected_components:
                        continue
                    selected_components.add(impacted_id)
                    impact_reason[impacted_id] = f"impact of {component_id}"
                    queue.append(impacted_id)

        for component_id in sorted(selected_components):
            component = catalog.components[component_id]
            reason = impact_reason.get(component_id, f"direct match: {component_id}")
            for group_id in component.direct_groups:
                add_group(group_id, reason)

        for component_id in sorted(seed_components):
            component = catalog.components[component_id]
            if component.risk is Risk.GLOBAL:
                domain = (
                    Domain.REPOSITORY
                    if selected_tier is Tier.AFFECTED
                    else component.domain
                )
                add_fallback(domain, f"global-risk component: {component_id}")
            elif component.risk is Risk.HIGH and selected_tier is Tier.AFFECTED:
                add_fallback(component.domain, f"high-risk component: {component_id}")

    ordered_group_ids: list[str] = []
    ordered_seen: set[str] = set()

    def append_with_dependencies(group_id: str) -> None:
        if group_id in ordered_seen:
            return
        for dependency_id in sorted(catalog.groups[group_id].depends_on):
            append_with_dependencies(dependency_id)
        ordered_seen.add(group_id)
        ordered_group_ids.append(group_id)

    for group_id in sorted(reasons):
        append_with_dependencies(group_id)

    planned_groups = tuple(
        PlannedGroup(
            id=group_id,
            domain=group.domain,
            kind=group.kind,
            runner=group.runner,
            isolation=group.isolation,
            capabilities=group.capabilities,
            depends_on=group.depends_on,
            artifacts=group.artifacts,
            required=group.required,
            reasons=tuple(sorted(reasons[group_id])),
        )
        for group_id in ordered_group_ids
        for group in (catalog.groups[group_id],)
    )
    capabilities: frozenset[Capability] = frozenset(
        capability
        for group in planned_groups
        for capability in group.capabilities
        if group.required
    )

    plan = VerificationPlan(
        tier=selected_tier,
        source=change_set.source,
        base_sha=change_set.base_sha,
        head_sha=change_set.head_sha,
        changes=change_set.changes,
        groups=planned_groups,
        required_capabilities=capabilities,
        fallbacks=tuple(sorted(set(fallbacks))),
        manifest_hash=loaded.manifest_hash,
        plan_hash="0" * 64,
    )
    return plan.model_copy(update={"plan_hash": verification_plan_hash(plan)})
