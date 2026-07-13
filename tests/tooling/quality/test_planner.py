from __future__ import annotations

from pathlib import Path

from tooling.quality.change_sources import from_paths
from tooling.quality.manifest import load_catalog
from tooling.quality.models import Change, ChangeSet, ChangeStatus, Tier
from tooling.quality.planner import plan_verification

ROOT = Path(__file__).resolve().parents[3]


def _catalog():
    return load_catalog(ROOT / "tooling" / "quality.yml")


def _group_ids(plan) -> list[str]:
    return [group.id for group in plan.groups]


def test_quick_selects_direct_server_groups_without_impact_expansion() -> None:
    changes = from_paths(
        ["src/animetta/orchestration/server/handlers/chat_handlers.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.QUICK)

    assert _group_ids(plan) == ["backend-route-smoke", "backend-server-unit"]
    assert "backend-graph-unit" not in _group_ids(plan)


def test_quick_always_includes_catalogued_required_smoke() -> None:
    changes = from_paths(
        ["src/animetta/orchestration/graph/dialogue_nodes.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.QUICK)

    assert "backend-graph-unit" in _group_ids(plan)
    smoke = next(group for group in plan.groups if group.id == "backend-route-smoke")
    assert "required quick policy" in smoke.reasons


def test_affected_expands_declared_component_impacts() -> None:
    changes = from_paths(
        ["src/animetta/orchestration/server/handlers/chat_handlers.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert set(_group_ids(plan)) == {
        "backend-route-smoke",
        "backend-server-unit",
        "backend-graph-unit",
    }
    graph = next(group for group in plan.groups if group.id == "backend-graph-unit")
    assert any("impact" in reason for reason in graph.reasons)


def test_affected_high_risk_component_adds_domain_fallback() -> None:
    changes = from_paths(
        ["src/animetta/core/service_pool.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert "backend-full" in _group_ids(plan)
    assert any("high-risk" in fallback for fallback in plan.fallbacks)


def test_full_selects_each_hermetic_full_group_once() -> None:
    changes = from_paths([], repo_root=ROOT)

    plan = plan_verification(_catalog(), changes, Tier.FULL)
    ids = _group_ids(plan)

    assert ids.count("backend-full") == 1
    assert "backend-core-unit" not in ids
    assert {
        "backend-typecheck",
        "security-secrets",
        "frontend-tests",
        "frontend-typecheck",
        "frontend-build",
        "docker-compose-contract",
    }.issubset(ids)
    assert ids.count("backend-full") == 1
    assert "docker" in {capability.value for capability in plan.required_capabilities}


def test_nightly_extends_full_with_service_groups() -> None:
    changes = from_paths([], repo_root=ROOT)

    plan = plan_verification(_catalog(), changes, Tier.NIGHTLY)

    assert "backend-full" in _group_ids(plan)
    assert "docker-compose-contract" in _group_ids(plan)
    assert "docker" in {capability.value for capability in plan.required_capabilities}


def test_unknown_backend_path_falls_back_to_backend_full() -> None:
    changes = from_paths(
        ["src/animetta/new_area/feature.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.QUICK)

    assert {
        "backend-static",
        "backend-typecheck",
        "backend-route-smoke",
        "backend-events-contract",
        "backend-full",
    } == set(_group_ids(plan))
    assert any("unknown backend path" in fallback for fallback in plan.fallbacks)


def test_rename_to_unknown_production_path_triggers_new_path_fallback() -> None:
    changes = ChangeSet(
        changes=(
            Change(
                path="src/animetta/new_area/moved.py",
                old_path="src/animetta/orchestration/graph/old.py",
                status=ChangeStatus.RENAMED,
            ),
        ),
        source="worktree",
    )

    plan = plan_verification(_catalog(), changes, Tier.QUICK)

    assert "backend-graph-unit" in _group_ids(plan)
    assert "backend-full" in _group_ids(plan)
    assert any(
        "unknown backend path: src/animetta/new_area/moved.py" in fallback
        for fallback in plan.fallbacks
    )


def test_global_change_escalates_affected_plan_to_repository_full() -> None:
    changes = from_paths(["pyproject.toml"], repo_root=ROOT)

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert {
        "backend-full",
        "frontend-tests",
        "frontend-typecheck",
        "frontend-build",
    }.issubset(_group_ids(plan))
    assert any("global-risk" in fallback for fallback in plan.fallbacks)


def test_discovery_failure_falls_back_to_repository_full() -> None:
    changes = from_paths([], repo_root=ROOT)

    plan = plan_verification(
        _catalog(),
        changes,
        Tier.AFFECTED,
        discovery_failure="unable to resolve revision 'missing-base'",
    )

    assert "backend-full" in _group_ids(plan)
    assert any("discovery failure" in fallback for fallback in plan.fallbacks)


def test_full_discovery_failure_keeps_every_full_policy_group() -> None:
    changes = from_paths([], repo_root=ROOT)

    plan = plan_verification(
        _catalog(),
        changes,
        Tier.FULL,
        discovery_failure="unable to resolve before revision",
    )

    assert {
        "backend-full",
        "backend-static",
        "docs-contract",
        "frontend-tests",
        "frontend-typecheck",
        "frontend-build",
    }.issubset(_group_ids(plan))
    assert any("discovery failure" in fallback for fallback in plan.fallbacks)


def test_identical_inputs_produce_identical_plan_hash() -> None:
    changes = from_paths(
        ["src/animetta/orchestration/server/routes.py"],
        repo_root=ROOT,
    )
    loaded = _catalog()

    first = plan_verification(loaded, changes, Tier.AFFECTED)
    second = plan_verification(loaded, changes, Tier.AFFECTED)

    assert first == second
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_execution_dependencies_are_frozen_before_dependents(tmp_path: Path) -> None:
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
groups:
  a-dependent:
    domain: repository
    kind: contract
    runner: python
    entrypoint: dependent.py
    depends_on: [z-prerequisite]
  z-prerequisite:
    domain: repository
    kind: smoke
    runner: python
    entrypoint: prerequisite.py
components:
  source:
    domain: repository
    paths: [src/**]
    direct_groups: [a-dependent]
fallbacks:
  backend: [z-prerequisite]
  frontend: [z-prerequisite]
  repository: [z-prerequisite]
""".strip(),
        encoding="utf-8",
    )

    plan = plan_verification(
        load_catalog(manifest),
        from_paths(["src/example.py"], repo_root=tmp_path),
        Tier.QUICK,
    )

    assert _group_ids(plan) == ["z-prerequisite", "a-dependent"]
