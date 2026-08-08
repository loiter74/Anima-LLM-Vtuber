from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tooling.quality import planner as quality_planner
from tooling.quality.aggregate import aggregate_results
from tooling.quality.change_sources import from_paths
from tooling.quality.evidence import write_plan
from tooling.quality.manifest import load_catalog
from tooling.quality.models import (
    AggregateStatus,
    Change,
    ChangeSet,
    ChangeStatus,
    ResultStatus,
    Tier,
    VerificationPlan,
    VerificationResult,
)
from tooling.quality.planner import plan_verification

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolate_production_catalog_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep planner-selection tests independent of the real worktree size."""
    minimal_root = tmp_path / "minimal-repository"
    minimal_root.mkdir()
    production_manifest = (ROOT / "tooling" / "quality.yml").resolve()
    original_repository_root = quality_planner._repository_root

    def repository_root(manifest_path: Path) -> Path:
        if manifest_path.resolve() == production_manifest:
            return minimal_root
        return original_repository_root(manifest_path)

    monkeypatch.setattr(quality_planner, "_repository_root", repository_root)


def _catalog():
    return load_catalog(ROOT / "tooling" / "quality.yml")


def _group_ids(plan) -> list[str]:
    return [group.id for group in plan.groups]


def _passing_results(plan: VerificationPlan) -> tuple[VerificationResult, ...]:
    return tuple(
        VerificationResult(
            group_id=group.id,
            required=group.required,
            status=ResultStatus.PASSED,
            exit_code=0,
            duration_seconds=0,
            plan_hash=plan.plan_hash,
            manifest_hash=plan.manifest_hash,
            input_fingerprint=group.input_fingerprint,
        )
        for group in plan.groups
    )


def _representative_change_set(case: str) -> ChangeSet:
    paths_by_case = {
        "backend": ["src/animetta/orchestration/server/handlers/chat_handlers.py"],
        "frontend": ["frontend/src/components/chat/MessageBubble.vue"],
        "mixed": [
            "src/animetta/orchestration/graph/dialogue_nodes.py",
            "frontend/src/components/chat/MessageBubble.vue",
        ],
        "high-risk": ["src/animetta/core/service_pool.py"],
        "global": ["pyproject.toml"],
        "unknown": ["src/animetta/new_area/feature.py"],
    }
    if case in paths_by_case:
        return from_paths(paths_by_case[case], repo_root=ROOT)
    if case == "rename":
        return ChangeSet(
            changes=(
                Change(
                    path="src/animetta/new_area/moved.py",
                    old_path="src/animetta/orchestration/graph/old.py",
                    status=ChangeStatus.RENAMED,
                ),
            ),
            source="worktree",
        )
    raise AssertionError(f"unknown representative case: {case}")


def test_quick_selects_direct_server_groups_without_impact_expansion() -> None:
    changes = from_paths(
        ["src/animetta/orchestration/server/handlers/chat_handlers.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.QUICK)

    assert _group_ids(plan) == [
        "backend-deadcode",
        "backend-route-smoke",
        "backend-server-unit",
        "backend-static",
        "backend-typecheck",
        "python-format",
    ]
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
        "backend-deadcode",
        "backend-route-smoke",
        "backend-server-unit",
        "backend-graph-unit",
        "backend-static",
        "backend-typecheck",
        "python-format",
    }
    graph = next(group for group in plan.groups if group.id == "backend-graph-unit")
    assert any("impact" in reason for reason in graph.reasons)


def test_embedded_javascript_selects_the_source_boundary_gate() -> None:
    changes = from_paths(
        ["src/animetta/tools/embedded.mjs"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert "operational-source-contract" in _group_ids(plan)


def test_affected_high_risk_component_adds_domain_fallback() -> None:
    changes = from_paths(
        ["src/animetta/core/service_pool.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert "backend-full" in _group_ids(plan)
    assert any("high-risk" in fallback for fallback in plan.fallbacks)


def test_backend_full_explicitly_dominates_selected_focused_pytest_groups() -> None:
    changes = from_paths(
        ["src/animetta/core/service_pool.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)
    dominated = {item.id: item.covering_group for item in plan.dominated_groups}

    assert "backend-full" in _group_ids(plan)
    assert "backend-core-unit" not in _group_ids(plan)
    assert dominated["backend-core-unit"] == "backend-full"
    assert dominated["backend-server-unit"] == "backend-full"
    assert dominated["backend-graph-unit"] == "backend-full"
    assert "backend-route-smoke" in _group_ids(plan)
    assert "backend-static" in _group_ids(plan)


def test_sequential_shadow_plan_can_disable_dominance() -> None:
    changes = from_paths(
        ["src/animetta/core/service_pool.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(
        _catalog(),
        changes,
        Tier.AFFECTED,
        apply_dominance=False,
    )

    assert "backend-full" in _group_ids(plan)
    assert "backend-core-unit" in _group_ids(plan)
    assert plan.dominated_groups == ()


@pytest.mark.parametrize(
    ("path", "required_group"),
    [
        ("tooling/quality/cli.py", "backend-tooling-quality"),
        ("scripts/runtime_lifecycle.py", "runtime-lifecycle-unit"),
        ("scripts/minecraft_adaptive_showcase.py", "minecraft-adaptive-mission-unit"),
        ("scripts/minecraft_adaptive_micro_gate.py", "minecraft-adaptive-mission-unit"),
        ("tests/core/test_socketio_server.py", "backend-core-unit"),
    ],
)
def test_focused_operational_changes_do_not_expand_to_repository_fallback(
    path: str,
    required_group: str,
) -> None:
    plan = plan_verification(
        _catalog(),
        from_paths([path], repo_root=ROOT),
        Tier.AFFECTED,
    )
    selected = _group_ids(plan)

    assert required_group in selected
    assert "backend-full" not in selected
    assert "frontend-build" not in selected
    assert "minecraft-real-conversation" not in selected
    assert "minecraft-real-showcase" not in selected


@pytest.mark.parametrize(
    "case",
    ["backend", "frontend", "mixed", "high-risk", "global", "rename", "unknown"],
)
def test_accelerated_and_sequential_shadow_plans_preserve_required_outcomes(
    case: str,
) -> None:
    loaded = _catalog()
    changes = _representative_change_set(case)

    accelerated = plan_verification(
        loaded,
        changes,
        Tier.AFFECTED,
        apply_dominance=True,
    )
    sequential = plan_verification(
        loaded,
        changes,
        Tier.AFFECTED,
        apply_dominance=False,
    )

    accelerated_ids = set(_group_ids(accelerated))
    sequential_ids = set(_group_ids(sequential))
    dominated = {item.id: item.covering_group for item in accelerated.dominated_groups}

    assert sequential_ids == accelerated_ids | set(dominated)
    assert set(dominated.values()) <= accelerated_ids
    assert accelerated.changes == sequential.changes
    assert accelerated.fallbacks == sequential.fallbacks
    assert accelerated.docker_actions == sequential.docker_actions
    assert accelerated.required_capabilities == sequential.required_capabilities

    accelerated_fingerprints = {group.id: group.input_fingerprint for group in accelerated.groups}
    sequential_fingerprints = {group.id: group.input_fingerprint for group in sequential.groups}
    assert accelerated_fingerprints == {
        group_id: sequential_fingerprints[group_id] for group_id in accelerated_ids
    }

    accelerated_results = _passing_results(accelerated)
    sequential_results = _passing_results(sequential)
    accelerated_summary = aggregate_results(accelerated, accelerated_results)
    sequential_summary = aggregate_results(sequential, sequential_results)

    assert accelerated_summary.status is AggregateStatus.PASSED
    assert sequential_summary.status is AggregateStatus.PASSED
    assert {result.group_id: result.status for result in sequential_results} == {
        **{result.group_id: result.status for result in accelerated_results},
        **{
            group_id: next(
                result.status for result in accelerated_results if result.group_id == covering_group
            )
            for group_id, covering_group in dominated.items()
        },
    }
    assert accelerated_summary.dominated_groups == accelerated.dominated_groups


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


def test_full_selects_every_repository_code_standard_group() -> None:
    plan = plan_verification(_catalog(), from_paths([], repo_root=ROOT), Tier.FULL)

    assert {
        "backend-deadcode",
        "python-format",
        "backend-static",
        "backend-typecheck",
        "backend-support-typecheck",
        "frontend-deadcode",
        "frontend-duplicates",
        "frontend-lint",
        "frontend-format",
        "frontend-typecheck",
        "operational-source-contract",
    }.issubset(_group_ids(plan))


def test_nightly_extends_full_with_service_groups() -> None:
    changes = from_paths([], repo_root=ROOT)

    plan = plan_verification(_catalog(), changes, Tier.NIGHTLY)

    assert "backend-full" in _group_ids(plan)
    assert "docker-compose-contract" in _group_ids(plan)
    assert "docker" in {capability.value for capability in plan.required_capabilities}


def test_frozen_plan_records_selective_docker_actions() -> None:
    changes = from_paths(
        ["src/animetta_qwen_tts/app.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert [action.service for action in plan.docker_actions] == ["qwen-tts"]
    assert len(plan.docker_actions[0].input_fingerprint) == 64


def test_unknown_backend_path_falls_back_to_backend_full() -> None:
    changes = from_paths(
        ["src/animetta/new_area/feature.py"],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.QUICK)

    assert {
        "backend-deadcode",
        "python-format",
        "backend-static",
        "backend-typecheck",
        "backend-route-smoke",
        "backend-events-contract",
        "backend-full",
    } == set(_group_ids(plan))
    assert any("unknown backend path" in fallback for fallback in plan.fallbacks)


def test_unknown_fallback_path_is_bound_to_selected_group_fingerprints() -> None:
    changes = from_paths(["scripts/smoke_qwen_alice.py"], repo_root=ROOT)

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)
    backend_full = next(group for group in plan.groups if group.id == "backend-full")

    assert "scripts/smoke_qwen_alice.py" in backend_full.input_patterns
    assert backend_full.cacheable is True


def test_acceptance_audition_paths_use_dedicated_gate_without_unknown_fallback() -> None:
    changes = from_paths(
        [
            "src/animetta/acceptance/tts_audition/runner.py",
            "tests/acceptance/test_tts_audition_runner.py",
            "scripts/tts_audition.py",
            "scripts/README.md",
        ],
        repo_root=ROOT,
    )

    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)

    assert "backend-acceptance-unit" in _group_ids(plan)
    assert "docs-contract" in _group_ids(plan)
    assert "backend-full" not in _group_ids(plan)
    assert not any("unknown" in fallback for fallback in plan.fallbacks)


def test_deleted_and_renamed_fallback_changes_have_distinct_fingerprints(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
input_sets:
  toolchain:
    paths: [pyproject.toml]
default_input_sets: [toolchain]
groups:
  backend-full:
    domain: backend
    kind: contract
    runner: pytest
    targets: [tests]
components:
  source:
    domain: backend
    paths: [src/**]
    direct_groups: [backend-full]
fallbacks:
  backend: [backend-full]
  frontend: [backend-full]
  repository: [backend-full]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_placeholder.py").write_text(
        "def test_placeholder(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='fingerprint-test'\n",
        encoding="utf-8",
    )
    catalog = load_catalog(manifest)
    deleted = ChangeSet(
        changes=(Change(path="scripts/removed-smoke.py", status=ChangeStatus.DELETED),),
        source="worktree",
    )
    renamed = ChangeSet(
        changes=(
            Change(
                path="scripts/renamed-smoke.py",
                old_path="scripts/removed-smoke.py",
                status=ChangeStatus.RENAMED,
            ),
        ),
        source="worktree",
    )

    deleted_plan = plan_verification(catalog, deleted, Tier.AFFECTED)
    renamed_plan = plan_verification(catalog, renamed, Tier.AFFECTED)
    deleted_group = next(group for group in deleted_plan.groups if group.id == "backend-full")
    renamed_group = next(group for group in renamed_plan.groups if group.id == "backend-full")

    assert deleted_group.input_fingerprint != renamed_group.input_fingerprint
    assert "scripts/removed-smoke.py" in deleted_group.input_patterns
    assert {
        "scripts/removed-smoke.py",
        "scripts/renamed-smoke.py",
    }.issubset(renamed_group.input_patterns)


def test_discovery_failure_disables_fallback_cache_reuse() -> None:
    changes = from_paths([], repo_root=ROOT)

    plan = plan_verification(
        _catalog(),
        changes,
        Tier.AFFECTED,
        discovery_failure="unable to inspect worktree",
    )

    fallback_groups = [
        group
        for group in plan.groups
        if any(reason.startswith("discovery failure") for reason in group.reasons)
    ]
    assert fallback_groups
    assert all(not group.cacheable for group in fallback_groups)


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

    assert "backend-graph-unit" not in _group_ids(plan)
    assert "backend-full" in _group_ids(plan)
    assert any(
        dominated.id == "backend-graph-unit" and dominated.covering_group == "backend-full"
        for dominated in plan.dominated_groups
    )
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


def test_plan_hash_survives_cross_process_json_round_trip(tmp_path: Path) -> None:
    changes = from_paths(
        ["src/animetta/tools/minecraft/showcase/live.py"],
        repo_root=ROOT,
    )
    plan = plan_verification(_catalog(), changes, Tier.AFFECTED)
    plan_path = tmp_path / "plan.json"
    write_plan(plan, plan_path)
    script = (
        "from tooling.quality.evidence import read_plan; "
        "import sys; "
        "print(read_plan(sys.argv[1]).plan_hash)"
    )

    for seed in ("1", "2", "4", "7"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script, str(plan_path)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == plan.plan_hash


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


def test_plan_binds_group_content_fingerprints_into_stable_plan_hash(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
input_sets:
  toolchain:
    paths: [pyproject.toml]
default_input_sets: [toolchain]
groups:
  source-unit:
    domain: backend
    kind: unit
    runner: pytest
    targets: [tests/source]
    cacheable: true
components:
  source:
    domain: backend
    paths: [src/source/**]
    direct_groups: [source-unit]
fallbacks:
  backend: [source-unit]
  frontend: [source-unit]
  repository: [source-unit]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "src/source").mkdir(parents=True)
    (tmp_path / "tests/source").mkdir(parents=True)
    (tmp_path / "src/source/module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests/source/test_module.py").write_text(
        "def test_value(): pass\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    changes = from_paths(["src/source/module.py"], repo_root=tmp_path)

    first = plan_verification(load_catalog(manifest), changes, Tier.QUICK)
    first_group = first.groups[0]
    assert len(first_group.input_fingerprint) == 64
    assert first_group.input_file_count == 3
    assert first_group.fingerprint_schema_version == 1

    (tmp_path / "src/source/module.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = plan_verification(load_catalog(manifest), changes, Tier.QUICK)

    assert second.groups[0].input_fingerprint != first_group.input_fingerprint
    assert second.plan_hash != first.plan_hash
