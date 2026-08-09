from __future__ import annotations

from collections import deque
from pathlib import Path

from .docker_plan import compose_identity, plan_docker_actions
from .fingerprint import (
    FINGERPRINT_SCHEMA_VERSION,
    FingerprintContext,
    GroupFingerprint,
    fingerprint_group,
    is_safe_fingerprint_pattern,
)
from .hashing import canonical_json_hash
from .manifest import LoadedCatalog
from .models import (
    Capability,
    Change,
    ChangeSet,
    Domain,
    DominatedGroup,
    PlannedGroup,
    Risk,
    Tier,
    VerificationPlan,
)
from .path_matching import matches_repository_path


def matching_components(loaded: LoadedCatalog, path: str) -> tuple[str, ...]:
    normalized = path.replace("\\", "/")
    return tuple(
        sorted(
            component_id
            for component_id, component in loaded.catalog.components.items()
            if any(matches_repository_path(normalized, pattern) for pattern in component.paths)
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
    return canonical_json_hash(payload)


def _repository_root(manifest_path: Path) -> Path:
    start = manifest_path.resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start.parent if start.name == "tooling" else start


def verification_plan_hash(plan: VerificationPlan) -> str:
    payload = {
        "schema_version": plan.schema_version,
        "tier": plan.tier.value,
        "source": plan.source,
        "base_sha": plan.base_sha,
        "head_sha": plan.head_sha,
        "changes": plan.changes,
        "groups": plan.groups,
        "required_capabilities": plan.required_capabilities,
        "fallbacks": sorted(plan.fallbacks),
        "dominated_groups": plan.dominated_groups,
        "docker_actions": plan.docker_actions,
        "docker_scope_fingerprints": dict(sorted(plan.docker_scope_fingerprints.items())),
        "compose_identity": plan.compose_identity,
        "scheduler": plan.scheduler,
        "manifest_hash": plan.manifest_hash,
    }
    return _plan_hash(payload)


def plan_verification(
    loaded: LoadedCatalog,
    change_set: ChangeSet,
    tier: Tier | str,
    *,
    discovery_failure: str | None = None,
    apply_dominance: bool = True,
) -> VerificationPlan:
    selected_tier = Tier(tier)
    catalog = loaded.catalog
    reasons: dict[str, set[str]] = {}
    fallbacks: list[str] = []
    fallback_changes: dict[str, dict[tuple[str, str, str], Change]] = {}
    cache_disabled_groups: set[str] = set()

    def add_group(group_id: str, reason: str) -> None:
        reasons.setdefault(group_id, set()).add(reason)
        for dependency_id in catalog.groups[group_id].depends_on:
            add_group(dependency_id, f"execution dependency of {group_id}")

    def add_fallback(
        domain: Domain,
        reason: str,
        *,
        changes: tuple[Change, ...] = (),
        disable_cache: bool = False,
    ) -> None:
        fallbacks.append(reason)
        for group_id in catalog.fallbacks.for_domain(domain):
            add_group(group_id, reason)
            by_identity = fallback_changes.setdefault(group_id, {})
            for change in changes:
                key = (change.path, change.status.value, change.old_path or "")
                by_identity[key] = change
            if disable_cache:
                cache_disabled_groups.add(group_id)

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
            cache_disabled_groups.update(reasons)
        else:
            add_fallback(Domain.REPOSITORY, reason, disable_cache=True)
            if "backend-full" in catalog.groups:
                add_group("backend-full", reason)
                cache_disabled_groups.add("backend-full")
    elif selected_tier in {Tier.FULL, Tier.NIGHTLY}:
        add_full_policy()
    else:
        seed_components: set[str] = set()
        for change in change_set.changes:
            matched_for_change: set[str] = set()
            for path in _change_paths(change):
                matched_for_path: set[str] = set()
                for component_id, component in catalog.components.items():
                    if any(matches_repository_path(path, pattern) for pattern in component.paths):
                        matched_for_path.add(component_id)
                if not matched_for_path:
                    domain = _infer_domain(path)
                    add_fallback(
                        domain,
                        f"unknown {domain.value} path: {path}",
                        changes=(change,),
                    )
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
                domain = Domain.REPOSITORY if selected_tier is Tier.AFFECTED else component.domain
                add_fallback(
                    domain,
                    f"global-risk component: {component_id}",
                    changes=change_set.changes,
                )
            elif component.risk is Risk.HIGH and selected_tier is Tier.AFFECTED:
                add_fallback(
                    component.domain,
                    f"high-risk component: {component_id}",
                    changes=change_set.changes,
                )

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

    dominated_groups: tuple[DominatedGroup, ...] = ()
    if apply_dominance:
        selected_ids = set(ordered_group_ids)
        coverage_closure: dict[str, set[str]] = {}

        def covered_by(group_id: str) -> set[str]:
            cached = coverage_closure.get(group_id)
            if cached is not None:
                return cached
            covered: set[str] = set()
            for covered_id in catalog.groups[group_id].covers:
                covered.add(covered_id)
                covered.update(covered_by(covered_id))
            coverage_closure[group_id] = covered
            return covered

        dependency_ids = {
            dependency_id
            for selected_id in selected_ids
            for dependency_id in catalog.groups[selected_id].depends_on
        }
        maximal_coverers = {
            group_id
            for group_id in selected_ids
            if not any(
                group_id in covered_by(other_id)
                for other_id in selected_ids
                if other_id != group_id
            )
        }
        dominated: list[DominatedGroup] = []
        for covered_id in sorted(selected_ids - dependency_ids):
            coverers = [
                covering_id
                for covering_id in maximal_coverers
                if covered_id in covered_by(covering_id)
            ]
            if not coverers:
                continue
            covering_id = sorted(
                coverers,
                key=lambda candidate: (-len(covered_by(candidate)), candidate),
            )[0]
            dominated.append(
                DominatedGroup(
                    id=covered_id,
                    covering_group=covering_id,
                    reasons=(f"explicitly covered by selected group {covering_id}",),
                )
            )
        dominated_groups = tuple(dominated)
        dominated_ids = {group.id for group in dominated_groups}
        ordered_group_ids = [
            group_id for group_id in ordered_group_ids if group_id not in dominated_ids
        ]

    fingerprint_context = FingerprintContext(_repository_root(loaded.path))
    group_fingerprints: dict[str, GroupFingerprint] = {}
    planned_group_list: list[PlannedGroup] = []
    for group_id in ordered_group_ids:
        group = catalog.groups[group_id]
        dependency_fingerprints = {
            dependency_id: group_fingerprints[dependency_id].digest
            for dependency_id in group.depends_on
        }
        related_changes = tuple(
            change for _, change in sorted(fallback_changes.get(group_id, {}).items())
        )
        extra_input_patterns = tuple(
            sorted(
                {
                    path
                    for change in related_changes
                    for path in _change_paths(change)
                    if is_safe_fingerprint_pattern(path)
                }
            )
        )
        if any(
            not is_safe_fingerprint_pattern(path)
            for change in related_changes
            for path in _change_paths(change)
        ):
            cache_disabled_groups.add(group_id)
        fingerprint = fingerprint_group(
            fingerprint_context,
            catalog,
            loaded.manifest_hash,
            group_id,
            dependency_fingerprints,
            extra_input_patterns=extra_input_patterns,
            change_identity=related_changes,
        )
        group_fingerprints[group_id] = fingerprint
        planned_group_list.append(
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
                cacheable=group.cacheable and group_id not in cache_disabled_groups,
                resource_class=group.resource_class,
                resource_weight=group.resource_weight,
                fingerprint_schema_version=FINGERPRINT_SCHEMA_VERSION,
                input_fingerprint=fingerprint.digest,
                input_file_count=fingerprint.file_count,
                input_patterns=fingerprint.patterns,
                toolchain_identity=fingerprint.toolchain_identity,
            )
        )
    planned_groups = tuple(planned_group_list)
    capabilities: frozenset[Capability] = frozenset(
        capability
        for group in planned_groups
        for capability in group.capabilities
        if group.required
    )
    docker_actions = plan_docker_actions(
        catalog,
        change_set,
        selected_tier,
        fingerprint_context,
    )
    docker_scope_fingerprints = {
        action.scope_id: action.input_fingerprint for action in docker_actions
    }
    current_compose_identity = compose_identity(catalog, fingerprint_context)

    plan = VerificationPlan(
        tier=selected_tier,
        source=change_set.source,
        base_sha=change_set.base_sha,
        head_sha=change_set.head_sha,
        changes=change_set.changes,
        groups=planned_groups,
        required_capabilities=capabilities,
        fallbacks=tuple(sorted(set(fallbacks))),
        dominated_groups=dominated_groups,
        docker_actions=docker_actions,
        docker_scope_fingerprints=docker_scope_fingerprints,
        compose_identity=current_compose_identity,
        scheduler=catalog.scheduler,
        manifest_hash=loaded.manifest_hash,
        plan_hash="0" * 64,
    )
    return plan.model_copy(update={"plan_hash": verification_plan_hash(plan)})
