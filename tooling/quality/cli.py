from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from tooling.execution_feedback import FeedbackStatus

from .aggregate import aggregate_results
from .benchmark import BenchmarkEvidence, BenchmarkRun, percentile
from .cache import ResultCache, artifact_digest
from .change_sources import ChangeDiscoveryError, discover_range, discover_worktree, from_paths
from .docker_plan import compose_identity, fingerprint_docker_scopes
from .evidence import read_plan, read_results, write_plan, write_summary
from .executor import collect_pytest_test_ids, run_group, write_result
from .feedback import (
    QualityShardResult,
    QualityShardSpec,
    freeze_quality_feedback_plan,
    run_feedback_schedule,
)
from .fingerprint import FingerprintContext
from .manifest import LoadedCatalog, load_catalog
from .models import (
    AggregateStatus,
    AggregateSummary,
    CacheMode,
    ChangeSet,
    ResultStatus,
    Runner,
    SchedulerPolicy,
    Tier,
    TrustScope,
    VerificationPlan,
    VerificationResult,
)
from .planner import matching_components, plan_verification
from .warm_topology import (
    TopologyCollectionError,
    collect_desired_environment_identities,
    collect_service_observations,
    create_warm_topology_stamp,
    evaluate_warm_topology,
    load_warm_topology_stamp,
    probe_runtime_readiness,
    write_warm_topology_stamp,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "tooling" / "quality.yml"
MINIMUM_PYTHON = (3, 13)


def _add_catalog_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=ROOT)


def _add_change_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tier", choices=[tier.value for tier in Tier], required=True)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--paths", nargs="+")
    sources.add_argument("--worktree", action="store_true")
    sources.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--shadow-sequential", action="store_true")


def _add_execution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache", choices=[mode.value for mode in CacheMode])
    parser.add_argument(
        "--trust-scope",
        choices=[scope.value for scope in TrustScope],
    )
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--sequential", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tooling.quality")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    _add_catalog_arguments(validate)
    validate.add_argument("--json", action="store_true")

    explain = subparsers.add_parser("explain")
    explain.add_argument("path")
    _add_catalog_arguments(explain)
    explain.add_argument("--json", action="store_true")

    plan = subparsers.add_parser("plan")
    _add_catalog_arguments(plan)
    _add_change_arguments(plan)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--github-output", type=Path)
    plan.add_argument("--json", action="store_true")

    verify = subparsers.add_parser("verify")
    _add_catalog_arguments(verify)
    _add_change_arguments(verify)
    verify.add_argument("--plan-output", type=Path)
    verify.add_argument("--results-dir", type=Path)
    _add_execution_arguments(verify)
    verify.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run")
    _add_catalog_arguments(run)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--results-dir", type=Path)
    _add_execution_arguments(run)
    run.add_argument("--json", action="store_true")

    run_one = subparsers.add_parser("run-group")
    run_one.add_argument("group_id")
    _add_catalog_arguments(run_one)
    run_one.add_argument("--plan", type=Path, required=True)
    run_one.add_argument("--output", type=Path)
    _add_execution_arguments(run_one)
    run_one.add_argument("--json", action="store_true")

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--plan", type=Path, required=True)
    aggregate.add_argument("--results-dir", type=Path, required=True)
    aggregate.add_argument("--output", type=Path)
    aggregate.add_argument("--json", action="store_true")

    docker_build = subparsers.add_parser("docker-build")
    _add_catalog_arguments(docker_build)
    docker_build.add_argument("--plan", type=Path, required=True)
    docker_build.add_argument("--compose-file", type=Path, action="append")
    docker_build.add_argument(
        "--no-cache",
        action="store_true",
        help="Force a cold Docker build for release-grade verification",
    )
    docker_build.add_argument("--json", action="store_true")

    warm_preflight = subparsers.add_parser("warm-preflight")
    _add_catalog_arguments(warm_preflight)
    warm_preflight.add_argument("--plan", type=Path, required=True)
    warm_preflight.add_argument("--stamp", type=Path, required=True)
    warm_preflight.add_argument("--ready-url", default="http://localhost/ready")
    warm_preflight.add_argument("--json", action="store_true")

    topology_stamp = subparsers.add_parser("topology-stamp")
    _add_catalog_arguments(topology_stamp)
    topology_stamp.add_argument("--plan", type=Path, required=True)
    topology_stamp.add_argument("--output", type=Path, required=True)
    topology_stamp.add_argument("--ready-url", default="http://localhost/ready")
    topology_stamp.add_argument("--json", action="store_true")

    benchmark = subparsers.add_parser("benchmark")
    _add_catalog_arguments(benchmark)
    _add_change_arguments(benchmark)
    benchmark.add_argument("--iterations", type=int, default=5)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--json", action="store_true")
    return parser


def _json_text(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=True)


def _load_checked_catalog(args: argparse.Namespace) -> LoadedCatalog:
    return load_catalog(args.manifest)


def _discover_changes(args: argparse.Namespace) -> tuple[ChangeSet, str | None]:
    if args.paths is not None:
        return from_paths(args.paths, repo_root=args.repo_root), None
    if args.base_sha:
        if not args.head_sha:
            raise ValueError("--head-sha is required with --base-sha")
        try:
            return discover_range(args.repo_root, args.base_sha, args.head_sha), None
        except ChangeDiscoveryError as exc:
            return (
                ChangeSet(
                    changes=(),
                    source="range",
                    base_sha=args.base_sha,
                    head_sha=args.head_sha,
                ),
                str(exc),
            )
    if args.head_sha:
        raise ValueError("--base-sha is required with --head-sha")
    try:
        return discover_worktree(args.repo_root), None
    except ChangeDiscoveryError as exc:
        return ChangeSet(changes=(), source="worktree"), str(exc)


def _environment_groups(plan: VerificationPlan) -> dict[str, list[str]]:
    matrices: dict[str, list[str]] = {"python": [], "node": [], "service": []}
    for group in plan.groups:
        if group.isolation.value != "hermetic" or group.runner in {
            Runner.PLAYWRIGHT,
            Runner.DOCKER,
        }:
            matrices["service"].append(group.id)
        elif group.runner in {Runner.PNPM, Runner.VITEST}:
            matrices["node"].append(group.id)
        else:
            matrices["python"].append(group.id)
    return matrices


def _write_github_outputs(plan: VerificationPlan, path: Path) -> None:
    matrices = _environment_groups(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for environment, groups in matrices.items():
            handle.write(
                f"{environment}_groups="
                f"{json.dumps(groups, ensure_ascii=True, separators=(',', ':'))}\n"
            )
            handle.write(f"has_{environment}={'true' if groups else 'false'}\n")
        handle.write(f"plan_hash={plan.plan_hash}\n")
        docker_services = [action.service for action in plan.docker_actions]
        handle.write(
            "docker_services="
            f"{json.dumps(docker_services, ensure_ascii=True, separators=(',', ':'))}\n"
        )
        handle.write(f"has_docker_build={'true' if docker_services else 'false'}\n")


def _command_validate(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    payload = {
        "valid": True,
        "schema_version": loaded.catalog.schema_version,
        "manifest_hash": loaded.manifest_hash,
        "groups": len(loaded.catalog.groups),
        "components": len(loaded.catalog.components),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(
            f"Manifest valid: {payload['groups']} groups, "
            f"{payload['components']} components ({loaded.manifest_hash[:12]})"
        )
    return 0


def _command_explain(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    components = matching_components(loaded, args.path)
    plan = plan_verification(
        loaded,
        from_paths([args.path], repo_root=args.repo_root),
        Tier.QUICK,
    )
    payload = {
        "path": args.path.replace("\\", "/"),
        "components": list(components),
        "groups": [group.id for group in plan.groups],
        "fallbacks": list(plan.fallbacks),
        "reasons": {group.id: list(group.reasons) for group in plan.groups},
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(f"Path: {payload['path']}")
        print(f"Components: {', '.join(components) or '(fallback)'}")
        for group in plan.groups:
            print(f"- {group.id}: {', '.join(group.reasons)}")
    return 0


def _command_plan(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    changes, discovery_failure = _discover_changes(args)
    plan = plan_verification(
        loaded,
        changes,
        Tier(args.tier),
        discovery_failure=discovery_failure,
        apply_dominance=not args.shadow_sequential,
    )
    if args.output:
        write_plan(plan, args.output)
    if args.github_output:
        _write_github_outputs(plan, args.github_output)
    if args.json:
        print(_json_text(plan))
    else:
        print(f"Plan {plan.plan_hash[:12]} ({plan.tier.value})")
        for group in plan.groups:
            print(f"- {group.id}: {', '.join(group.reasons)}")
        for fallback in plan.fallbacks:
            print(f"! fallback: {fallback}")
    return 0


def _ensure_manifest_matches(plan: VerificationPlan, loaded: LoadedCatalog) -> None:
    if plan.manifest_hash != loaded.manifest_hash:
        raise ValueError("plan manifest hash does not match current manifest")


def _results_directory(args: argparse.Namespace, plan: VerificationPlan) -> Path:
    return args.results_dir or (
        Path(args.repo_root) / "artifacts" / "test-impact" / plan.plan_hash / "results"
    )


def _invalidate_plan_evidence(
    results_dir: Path,
    plan: VerificationPlan,
) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    for group in plan.groups:
        (results_dir / f"{group.id}.json").unlink(missing_ok=True)
    (results_dir / "summary.json").unlink(missing_ok=True)


def _resolved_trust_scope(args: argparse.Namespace, plan: VerificationPlan) -> TrustScope:
    explicit = getattr(args, "trust_scope", None)
    if explicit:
        return TrustScope(explicit)
    event = os.environ.get("GITHUB_EVENT_NAME", "").casefold()
    if event == "pull_request":
        return TrustScope.PR
    if plan.tier in {Tier.FULL, Tier.NIGHTLY}:
        return TrustScope.RELEASE
    if event == "push" and os.environ.get("GITHUB_REF_NAME") == "main":
        return TrustScope.MAIN
    return TrustScope.LOCAL


def _resolved_cache_mode(args: argparse.Namespace, plan: VerificationPlan) -> CacheMode:
    explicit = getattr(args, "cache", None)
    if explicit:
        return CacheMode(explicit)
    if plan.tier in {Tier.FULL, Tier.NIGHTLY}:
        return CacheMode.OFF
    return CacheMode.READ_WRITE


def _cache_root(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "cache_root", None)
    if explicit:
        return Path(explicit)
    return Path(args.repo_root) / "artifacts" / "test-impact" / "cache-v1"


def _artifact_digest_map(
    repo_root: Path,
    artifacts: tuple[str, ...],
) -> dict[str, str]:
    digests: dict[str, str] = {}
    for artifact in artifacts:
        path = repo_root / artifact
        if not path.exists() or path.is_symlink():
            continue
        digest, _, _ = artifact_digest(path)
        digests[artifact] = digest
    return digests


def _execute_plan(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
    plan: VerificationPlan,
) -> tuple[AggregateStatus, AggregateSummary]:
    return _execute_feedback_plan(args, loaded, plan)


def _ensure_plan_is_executable(plan: VerificationPlan) -> None:
    if not plan.unmapped_paths:
        return
    paths = ", ".join(plan.unmapped_paths)
    raise ValueError(
        f"refusing to execute quality plan with unmapped repository paths: {paths}; "
        "add component mappings to the quality manifest and rerun"
    )


def _write_feedback_model(model: BaseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary basename short so atomic writes still work in deeply
    # nested Windows worktrees that are close to MAX_PATH.
    temporary = path.with_name(f"~{uuid.uuid4().hex[:8]}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(model.model_dump(mode="json"), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _feedback_test_ids(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
    plan: VerificationPlan,
    *,
    excluded_groups: frozenset[str] = frozenset(),
) -> dict[str, tuple[str, ...]]:
    discovered: dict[str, tuple[str, ...]] = {}
    repo_root = Path(args.repo_root).resolve()
    for planned in plan.groups:
        if planned.id in excluded_groups:
            continue
        group = loaded.catalog.groups[planned.id]
        if group.runner is Runner.PYTEST:
            discovered[planned.id] = collect_pytest_test_ids(
                loaded,
                planned.id,
                repo_root=args.repo_root,
            )
        elif group.runner is Runner.MYPY and group.targets:
            expanded: list[str] = []
            for target in group.targets:
                path = repo_root / target
                if not path.is_dir():
                    expanded.append(target)
                    continue
                children = tuple(
                    child
                    for child in sorted(path.iterdir(), key=lambda item: item.name.casefold())
                    if (child.is_file() and child.suffix == ".py")
                    or (child.is_dir() and any(child.rglob("*.py")))
                )
                expanded.extend(child.relative_to(repo_root).as_posix() for child in children)
            discovered[planned.id] = tuple(expanded)
        elif group.runner in {Runner.RUFF, Runner.RUFF_FORMAT} and group.targets:
            discovered[planned.id] = group.targets
    return discovered


def _feedback_estimates(
    loaded: LoadedCatalog,
    test_ids_by_group: dict[str, tuple[str, ...]],
    *,
    repo_root: Path,
) -> dict[str, dict[str, float]]:
    estimates: dict[str, dict[str, float]] = {}
    for group_id, test_ids in test_ids_by_group.items():
        if not test_ids:
            continue
        group = loaded.catalog.groups[group_id]
        declared_budget = float(group.timeout_seconds)
        if group.runner is Runner.MYPY:
            weights = {
                test_id: max(
                    1,
                    sum(1 for _ in (repo_root / test_id).rglob("*.py"))
                    if (repo_root / test_id).is_dir()
                    else 1,
                )
                for test_id in test_ids
            }
            total_weight = sum(weights.values())
            estimates[group_id] = {
                test_id: min(
                    239.0,
                    max(0.05, declared_budget * 2 * weight / total_weight),
                )
                for test_id, weight in weights.items()
            }
            continue
        per_test = min(239.0, max(0.05, declared_budget / len(test_ids)))
        estimates[group_id] = {test_id: per_test for test_id in test_ids}
    return estimates


def _coverage_groups(
    loaded: LoadedCatalog,
    plan: VerificationPlan,
) -> frozenset[str]:
    return frozenset(
        planned.id
        for planned in plan.groups
        if loaded.catalog.groups[planned.id].runner is Runner.PYTEST
        and loaded.catalog.groups[planned.id].artifacts
        and any(
            arg == "--cov" or arg.startswith("--cov=")
            for arg in loaded.catalog.groups[planned.id].args
        )
    )


def _load_prior_feedback_results(
    results_dir: Path,
    *,
    plan: VerificationPlan,
    excluded_groups: frozenset[str],
) -> tuple[QualityShardResult, ...]:
    recovered: list[QualityShardResult] = []
    for path in sorted((results_dir / "feedback").glob("*.json")):
        try:
            result = QualityShardResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            result.plan_hash == plan.plan_hash
            and result.manifest_hash == plan.manifest_hash
            and result.group_id not in excluded_groups
            and result.status is FeedbackStatus.PASSED
            and result.phase == "terminal"
        ):
            recovered.append(result)
    return tuple(recovered)


def _pytest_feedback_args(
    args: tuple[str, ...],
    *,
    append_coverage: bool,
) -> tuple[str, ...]:
    value_options_to_remove = {
        "-n",
        "--dist",
        "--max-worker-restart",
        "--numprocesses",
        "--tx",
    }
    prefixes_to_remove = tuple(f"{option}=" for option in value_options_to_remove)
    filtered: list[str] = []
    skip_next = False
    coverage_enabled = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in value_options_to_remove:
            skip_next = True
            continue
        if arg.startswith(prefixes_to_remove):
            continue
        if arg == "--cov":
            coverage_enabled = True
            filtered.append(arg)
            continue
        if arg.startswith("--cov="):
            coverage_enabled = True
            filtered.append(arg)
            continue
        if arg in {"--cov-report", "--cov-fail-under"}:
            skip_next = True
            continue
        if arg.startswith(("--cov-report=", "--cov-fail-under=")):
            continue
        if arg == "--cov-append":
            continue
        filtered.append(arg)
    if coverage_enabled:
        filtered.extend(("--cov-report=", "--cov-fail-under=0"))
        if append_coverage:
            filtered.append("--cov-append")
    return tuple(filtered)


def _coverage_fail_under(args: tuple[str, ...]) -> str:
    for index, arg in enumerate(args):
        if arg.startswith("--cov-fail-under="):
            return arg.split("=", 1)[1]
        if arg == "--cov-fail-under" and index + 1 < len(args):
            return args[index + 1]
    return "0"


def _run_coverage_feedback_shard(
    *,
    repo_root: Path,
    group_id: str,
    shard: QualityShardSpec,
    group_args: tuple[str, ...],
    artifacts: tuple[str, ...],
) -> QualityShardResult:
    started = time.perf_counter()
    outputs: list[str] = []
    commands = (
        (sys.executable, "-m", "coverage", "xml"),
        (
            sys.executable,
            "-m",
            "coverage",
            "report",
            f"--fail-under={_coverage_fail_under(group_args)}",
        ),
    )
    exit_code: int | None = 0
    status = FeedbackStatus.PASSED
    for command in commands:
        remaining = shard.action_budget_seconds - (time.perf_counter() - started)
        if remaining <= 0:
            status = FeedbackStatus.IN_PROGRESS
            exit_code = None
            break
        try:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=remaining,
            )
        except subprocess.TimeoutExpired as exc:
            outputs.extend(str(item) for item in (exc.stdout, exc.stderr) if item)
            status = FeedbackStatus.IN_PROGRESS
            exit_code = None
            break
        outputs.extend(item for item in (completed.stdout, completed.stderr) if item)
        if completed.returncode != 0:
            status = FeedbackStatus.FAILED
            exit_code = completed.returncode
            break
    completed_ids = (
        shard.test_ids if status in {FeedbackStatus.PASSED, FeedbackStatus.FAILED} else ()
    )
    remaining_ids = () if completed_ids else shard.test_ids
    existing_artifacts = tuple(
        artifact for artifact in artifacts if (repo_root / artifact).exists()
    )
    return QualityShardResult(
        plan_hash=shard.plan_hash,
        manifest_hash=shard.manifest_hash,
        group_id=group_id,
        shard_id=shard.shard_id,
        root_shard_id=shard.root_shard_id,
        status=status,
        test_ids=shard.test_ids,
        completed_test_ids=completed_ids,
        remaining_test_ids=remaining_ids,
        duration_seconds=min(time.perf_counter() - started, 300),
        evidence_refs=(f"quality-result:{group_id}:{shard.shard_id}",),
        artifacts=existing_artifacts,
        exit_code=exit_code,
        output="\n".join(outputs),
    )


def _execute_feedback_plan(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
    plan: VerificationPlan,
) -> tuple[AggregateStatus, AggregateSummary]:
    _ensure_plan_is_executable(plan)
    cache_mode = _resolved_cache_mode(args, plan)
    trust_scope = _resolved_trust_scope(args, plan)
    cache = None if cache_mode is CacheMode.OFF else ResultCache(_cache_root(args), args.repo_root)
    cached_groups: dict[str, VerificationResult] = {}
    cache_miss_reasons: dict[str, str] = {group.id: "cache-off" for group in plan.groups}
    if cache is not None:
        for group in plan.groups:
            lookup = cache.lookup(
                group,
                plan_hash=plan.plan_hash,
                manifest_hash=plan.manifest_hash,
                trust_scope=trust_scope,
            )
            if lookup.hit:
                assert lookup.result is not None
                cached_groups[group.id] = lookup.result
            else:
                cache_miss_reasons[group.id] = lookup.reason
    results_dir = _results_directory(args, plan)
    coverage_groups = _coverage_groups(loaded, plan)
    prior_results = _load_prior_feedback_results(
        results_dir,
        plan=plan,
        excluded_groups=coverage_groups,
    )
    _invalidate_plan_evidence(results_dir, plan)
    test_ids = _feedback_test_ids(
        args,
        loaded,
        plan,
        excluded_groups=frozenset(cached_groups),
    )
    estimates_by_group = _feedback_estimates(
        loaded,
        test_ids,
        repo_root=Path(args.repo_root).resolve(),
    )
    feedback_plan = freeze_quality_feedback_plan(
        plan,
        test_ids_by_group=test_ids,
        estimated_seconds_by_test={},
        estimated_seconds_by_group_test=estimates_by_group,
        coverage_groups=coverage_groups,
    )
    if getattr(args, "sequential", False) or getattr(args, "shadow_sequential", False):
        feedback_plan = feedback_plan.model_copy(
            update={
                "scheduler": SchedulerPolicy(
                    max_workers=1,
                    max_weight=plan.scheduler.max_weight,
                    max_heavy=1,
                    max_exclusive=1,
                )
            }
        )
    _write_feedback_model(feedback_plan, results_dir / "feedback-plan.json")
    cached_shard_results: list[QualityShardResult] = []
    for group_id, cached_result in cached_groups.items():
        group_shards = tuple(shard for shard in feedback_plan.shards if shard.group_id == group_id)
        for index, shard in enumerate(group_shards):
            cached_shard_results.append(
                QualityShardResult(
                    plan_hash=plan.plan_hash,
                    manifest_hash=plan.manifest_hash,
                    group_id=group_id,
                    shard_id=shard.shard_id,
                    root_shard_id=shard.root_shard_id,
                    status=FeedbackStatus.PASSED,
                    phase="terminal",
                    update_sequence=1,
                    test_ids=shard.test_ids,
                    completed_test_ids=shard.test_ids,
                    remaining_test_ids=(),
                    duration_seconds=0,
                    evidence_refs=(f"quality-cache:{cached_result.cache_source or group_id}",),
                    artifacts=cached_result.artifacts if index == len(group_shards) - 1 else (),
                    exit_code=0,
                    output="complete-group cache hit",
                )
            )

    def execute(
        shard: QualityShardSpec,
        cancellation: threading.Event,
    ) -> QualityShardResult:
        source_group = loaded.catalog.groups[shard.group_id]
        publish(
            QualityShardResult(
                plan_hash=plan.plan_hash,
                manifest_hash=plan.manifest_hash,
                group_id=shard.group_id,
                shard_id=shard.shard_id,
                root_shard_id=shard.root_shard_id,
                status=FeedbackStatus.IN_PROGRESS,
                phase="started",
                update_sequence=0,
                test_ids=shard.test_ids,
                completed_test_ids=(),
                remaining_test_ids=shard.test_ids,
                duration_seconds=0,
                evidence_refs=(f"quality-plan:{plan.plan_hash}:{shard.shard_id}",),
                output="feedback window started",
            )
        )
        if shard.operation == "coverage":
            return _run_coverage_feedback_shard(
                repo_root=Path(args.repo_root).resolve(),
                group_id=shard.group_id,
                shard=shard,
                group_args=source_group.args,
                artifacts=source_group.artifacts,
            )
        shard_args = (
            _pytest_feedback_args(
                source_group.args,
                append_coverage=shard.group_id in coverage_groups and shard.sequence > 1,
            )
            if source_group.runner is Runner.PYTEST
            else source_group.args
        )

        def heartbeat(elapsed: float) -> None:
            publish(
                QualityShardResult(
                    plan_hash=plan.plan_hash,
                    manifest_hash=plan.manifest_hash,
                    group_id=shard.group_id,
                    shard_id=shard.shard_id,
                    root_shard_id=shard.root_shard_id,
                    status=FeedbackStatus.IN_PROGRESS,
                    phase="running",
                    update_sequence=max(1, int(elapsed // 60)),
                    test_ids=shard.test_ids,
                    completed_test_ids=(),
                    remaining_test_ids=shard.test_ids,
                    duration_seconds=min(elapsed, 300),
                    evidence_refs=(f"quality-result:{shard.group_id}:{shard.shard_id}:running",),
                    output=f"action still running after {elapsed:.1f} seconds",
                )
            )

        result = run_group(
            loaded,
            shard.group_id,
            plan_hash=plan.plan_hash,
            repo_root=args.repo_root,
            cancellation_event=cancellation,
            targets_override=None if shard.opaque else shard.test_ids,
            args_override=shard_args,
            timeout_seconds_override=int(shard.action_budget_seconds),
            progress_callback=heartbeat,
        )
        if result.status is ResultStatus.PASSED:
            status = FeedbackStatus.PASSED
            completed = shard.test_ids
            remaining: tuple[str, ...] = ()
        elif result.failure_kind == "timeout":
            status = FeedbackStatus.IN_PROGRESS
            completed = ()
            remaining = shard.test_ids
        elif result.status is ResultStatus.FAILED:
            status = FeedbackStatus.FAILED
            completed = shard.test_ids
            remaining = ()
        elif result.status is ResultStatus.CANCELLED:
            status = FeedbackStatus.CANCELLED
            completed = ()
            remaining = shard.test_ids
        else:
            status = FeedbackStatus.BLOCKED
            completed = ()
            remaining = shard.test_ids
        return QualityShardResult(
            plan_hash=plan.plan_hash,
            manifest_hash=plan.manifest_hash,
            group_id=shard.group_id,
            shard_id=shard.shard_id,
            root_shard_id=shard.root_shard_id,
            status=status,
            phase="terminal",
            update_sequence=max(1, int(result.duration_seconds // 60) + 1),
            test_ids=shard.test_ids,
            completed_test_ids=completed,
            remaining_test_ids=remaining,
            duration_seconds=min(result.duration_seconds, 300),
            evidence_refs=(f"quality-result:{shard.group_id}:{shard.shard_id}",),
            artifacts=() if shard.group_id in coverage_groups else result.artifacts,
            exit_code=result.exit_code,
            output=result.output or result.remediation,
        )

    def publish(result: QualityShardResult) -> None:
        _write_feedback_model(
            result,
            results_dir / "feedback" / f"{result.shard_id}.json",
        )
        event_key = hashlib.sha256(result.shard_id.encode("utf-8")).hexdigest()[:12]
        _write_feedback_model(
            result,
            results_dir / "events" / f"{event_key}-{result.update_sequence}-{result.phase}.json",
        )
        print(
            (
                f"Quality feedback: {result.shard_id} {result.status.value} "
                f"({result.duration_seconds:.1f}s)"
            ),
            file=sys.stderr,
            flush=True,
        )

    outcome = run_feedback_schedule(
        feedback_plan,
        execute,
        publish=publish,
        prior_results=(*prior_results, *cached_shard_results),
    )
    repo_root = Path(args.repo_root).resolve()
    outcome_by_group = {result.group_id: result for result in outcome.group_results}
    planned_by_id = {group.id: group for group in plan.groups}
    finalized: list[VerificationResult] = []
    for group in plan.groups:
        if group.id in cached_groups:
            finalized.append(cached_groups[group.id])
            continue
        result = outcome_by_group.get(group.id)
        if result is None:
            continue
        result = result.model_copy(
            update={
                "trust_scope": trust_scope,
                "cache_reason": cache_miss_reasons[group.id],
                "artifact_digests": _artifact_digest_map(repo_root, result.artifacts),
            }
        )
        if cache is not None and cache_mode is CacheMode.READ_WRITE:
            write = cache.store(planned_by_id[group.id], result, trust_scope)
            result = result.model_copy(
                update={
                    "cache_reason": (f"miss:{cache_miss_reasons[group.id]};write:{write.reason}")
                }
            )
        finalized.append(result)
    group_results = tuple(finalized)
    for result in group_results:
        write_result(result, results_dir / f"{result.group_id}.json")
    summary = aggregate_results(plan, group_results).model_copy(
        update={
            "wall_seconds": outcome.wall_seconds,
            "critical_path_seconds": outcome.critical_path_seconds,
            "planning_seconds": float(getattr(args, "planning_seconds", 0)),
        }
    )
    write_summary(summary, results_dir / "summary.json")
    return summary.status, summary


def _command_run(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    plan = read_plan(args.plan)
    _ensure_manifest_matches(plan, loaded)
    status, summary = _execute_plan(args, loaded, plan)
    if args.json:
        print(_json_text(summary))
    else:
        print(f"Quality result: {summary.status.value}")
    return 1 if status is AggregateStatus.FAILED else 0


def _command_verify(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    changes, discovery_failure = _discover_changes(args)
    planning_started = time.perf_counter()
    plan = plan_verification(
        loaded,
        changes,
        Tier(args.tier),
        discovery_failure=discovery_failure,
        apply_dominance=not args.shadow_sequential,
    )
    args.planning_seconds = time.perf_counter() - planning_started
    plan_output = args.plan_output or (
        Path(args.repo_root) / "artifacts" / "test-impact" / plan.plan_hash / "plan.json"
    )
    write_plan(plan, plan_output)
    if not args.json:
        print(f"Plan {plan.plan_hash[:12]} ({plan.tier.value})")
        for group in plan.groups:
            print(f"- {group.id}: {', '.join(group.reasons)}")
        for fallback in plan.fallbacks:
            print(f"! fallback: {fallback}")
        for dominated in plan.dominated_groups:
            print(f"~ {dominated.id}: covered by {dominated.covering_group}")
        for action in plan.docker_actions:
            print(f"# docker build {action.service}: {', '.join(action.reasons)}")
    status, summary = _execute_plan(args, loaded, plan)
    if args.json:
        print(_json_text(summary))
    else:
        print(f"Quality result: {summary.status.value}")
    return 1 if status is AggregateStatus.FAILED else 0


def _command_run_group(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    plan = read_plan(args.plan)
    _ensure_manifest_matches(plan, loaded)
    selected = {group.id: group for group in plan.groups}
    if args.group_id not in selected:
        print(f"group {args.group_id!r} is not selected by plan", file=sys.stderr)
        return 2
    output = args.output or (
        Path(args.repo_root)
        / "artifacts"
        / "test-impact"
        / plan.plan_hash
        / "results"
        / f"{args.group_id}.json"
    )
    group = selected[args.group_id].model_copy(update={"depends_on": ()})
    group_plan = plan.model_copy(
        update={
            "groups": (group,),
            "required_capabilities": group.capabilities,
            "dominated_groups": (),
            "docker_actions": (),
        }
    )
    execution_args = argparse.Namespace(**vars(args))
    execution_args.results_dir = output.parent
    _, _summary = _execute_feedback_plan(execution_args, loaded, group_plan)
    result_path = output.parent / f"{args.group_id}.json"
    result = VerificationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    if output != result_path:
        write_result(result, output)
    if args.json:
        print(_json_text(result))
    elif result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    return 0 if result.status in {ResultStatus.PASSED, ResultStatus.SKIPPED} else 1


def _command_aggregate(args: argparse.Namespace) -> int:
    plan = read_plan(args.plan)
    summary = aggregate_results(plan, read_results(args.results_dir))
    write_summary(summary, args.output or (args.results_dir / "summary.json"))
    if args.json:
        print(_json_text(summary))
    else:
        print(f"Quality result: {summary.status.value}")
    return 1 if summary.status is AggregateStatus.FAILED else 0


def _command_docker_build(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    plan = read_plan(args.plan)
    _ensure_manifest_matches(plan, loaded)
    actions = plan.docker_actions
    commands: list[list[str]] = []
    if args.compose_file:
        argv = ["docker", "compose"]
        for compose_file in args.compose_file:
            argv.extend(("-f", str(compose_file)))
        argv.append("build")
        if args.no_cache:
            argv.append("--no-cache")
        argv.extend(action.service for action in actions)
        commands.append(argv)
    else:
        actions_by_compose: dict[str, list[Any]] = {}
        for action in actions:
            actions_by_compose.setdefault(action.compose_file, []).append(action)
        for compose_file, compose_actions in sorted(actions_by_compose.items()):
            argv = [
                "docker",
                "compose",
                "-f",
                str((args.repo_root / compose_file).resolve()),
                "build",
            ]
            if args.no_cache:
                argv.append("--no-cache")
            argv.extend(action.service for action in compose_actions)
            commands.append(argv)
    payload = {
        "status": "no-build" if not actions else "pending",
        "actions": [action.model_dump(mode="json") for action in actions],
        "commands": commands,
        "exit_code": 0,
    }
    if not actions:
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=True))
        else:
            print("Docker build: no selected services")
        return 0
    environment = dict(os.environ)
    variable_by_scope = {
        "animetta": "ANIMETTA_BUILD_FINGERPRINT",
    }
    for action in actions:
        variable = variable_by_scope.get(action.scope_id)
        if variable is None:
            raise ValueError(f"Docker scope has no build fingerprint variable: {action.scope_id}")
        environment[variable] = action.input_fingerprint
    completed_commands: list[subprocess.CompletedProcess[str]] = []
    for argv in commands:
        completed = subprocess.run(
            argv,
            cwd=args.repo_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=7200,
        )
        completed_commands.append(completed)
        if completed.returncode != 0:
            break
    exit_code = next(
        (completed.returncode for completed in completed_commands if completed.returncode != 0),
        0,
    )
    payload["exit_code"] = exit_code
    payload["status"] = "passed" if exit_code == 0 else "failed"
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(
            f"Docker build: {payload['status']} ({', '.join(action.service for action in actions)})"
        )
        for completed in completed_commands:
            if completed.stdout:
                print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
            if completed.stderr:
                print(
                    completed.stderr,
                    file=sys.stderr,
                    end="" if completed.stderr.endswith("\n") else "\n",
                )
    return 0 if exit_code == 0 else 1


def _current_topology_inputs(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
) -> tuple[dict[str, str], str]:
    context = FingerprintContext(args.repo_root)
    by_scope = fingerprint_docker_scopes(loaded.catalog, context)
    by_service = {
        loaded.catalog.docker_scopes[scope_id].service: fingerprint
        for scope_id, fingerprint in by_scope.items()
    }
    return by_service, compose_identity(loaded.catalog, context)


def _validated_topology_plan(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
) -> VerificationPlan:
    plan = read_plan(args.plan)
    _ensure_manifest_matches(plan, loaded)
    return plan


def _environment_allowlists(loaded: LoadedCatalog) -> dict[str, tuple[str, ...]]:
    return {
        scope.service: scope.environment_identity_fields
        for scope in loaded.catalog.docker_scopes.values()
    }


def _service_compose_files(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
) -> dict[str, str]:
    return {
        scope.service: str((args.repo_root / scope.compose_file).resolve())
        for scope in loaded.catalog.docker_scopes.values()
    }


def _command_warm_preflight(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    plan = _validated_topology_plan(args, loaded)
    build_fingerprints, current_compose = _current_topology_inputs(args, loaded)
    if plan.compose_identity and plan.compose_identity != current_compose:
        raise ValueError("frozen plan compose identity no longer matches the repository")
    services = tuple(sorted(build_fingerprints))
    allowlists = _environment_allowlists(loaded)
    compose_files = _service_compose_files(args, loaded)
    try:
        observed = collect_service_observations(
            services,
            environment_allowlists=allowlists,
            compose_files=compose_files,
        )
        desired_environment = collect_desired_environment_identities(
            services,
            environment_allowlists=allowlists,
            compose_files=compose_files,
        )
    except TopologyCollectionError:
        observed = {}
        desired_environment = {}
    readiness = probe_runtime_readiness(args.ready_url)
    decision = evaluate_warm_topology(
        load_warm_topology_stamp(args.stamp),
        current_build_fingerprints=build_fingerprints,
        current_compose_identity=current_compose,
        desired_environment_identities=desired_environment,
        observed_services=observed,
        readiness=readiness,
    )
    if args.json:
        print(_json_text(decision))
    else:
        print(f"Warm topology: {decision.action}")
        for mismatch in decision.mismatches:
            print(f"- {mismatch}")
        print("Fresh evidence still required: " + ", ".join(decision.fresh_evidence_required))
    return 0 if decision.reusable else 1


def _command_topology_stamp(args: argparse.Namespace) -> int:
    loaded = _load_checked_catalog(args)
    plan = _validated_topology_plan(args, loaded)
    build_fingerprints, current_compose = _current_topology_inputs(args, loaded)
    if plan.compose_identity and plan.compose_identity != current_compose:
        raise ValueError("frozen plan compose identity no longer matches the repository")
    services = tuple(sorted(build_fingerprints))
    allowlists = _environment_allowlists(loaded)
    compose_files = _service_compose_files(args, loaded)
    observed = collect_service_observations(
        services,
        environment_allowlists=allowlists,
        compose_files=compose_files,
    )
    desired_environment = collect_desired_environment_identities(
        services,
        environment_allowlists=allowlists,
        compose_files=compose_files,
    )
    readiness = probe_runtime_readiness(args.ready_url)
    stamp = create_warm_topology_stamp(
        current_build_fingerprints=build_fingerprints,
        compose_identity=current_compose,
        desired_environment_identities=desired_environment,
        observed_services=observed,
        readiness=readiness,
    )
    write_warm_topology_stamp(stamp, args.output)
    if args.json:
        print(_json_text(stamp))
    else:
        print(f"Topology stamp written: {args.output}")
    return 0


def _command_benchmark(args: argparse.Namespace) -> int:
    if args.iterations < 1:
        raise ValueError("--iterations must be at least 1")
    selected_tier = Tier(args.tier)
    if selected_tier not in {Tier.QUICK, Tier.AFFECTED}:
        raise ValueError("benchmark supports only quick or affected tiers")
    loaded = _load_checked_catalog(args)
    changes, discovery_failure = _discover_changes(args)
    planning_started = time.perf_counter()
    plan = plan_verification(
        loaded,
        changes,
        selected_tier,
        discovery_failure=discovery_failure,
        apply_dominance=True,
    )
    planning_seconds = time.perf_counter() - planning_started
    args.planning_seconds = planning_seconds
    args.cache = CacheMode.READ_WRITE.value
    args.trust_scope = TrustScope.LOCAL.value
    args.sequential = False
    args.shadow_sequential = False
    benchmark_root = args.output.parent / f"benchmark-{plan.plan_hash[:12]}"
    args.cache_root = benchmark_root / "cache"
    args.output.unlink(missing_ok=True)
    stale_runs = (benchmark_root / "prime", *benchmark_root.glob("warm-*"))
    for stale_run in stale_runs:
        if stale_run.is_dir():
            shutil.rmtree(stale_run)
        else:
            stale_run.unlink(missing_ok=True)
    write_plan(plan, benchmark_root / "plan.json")

    args.results_dir = benchmark_root / "prime"
    priming_status, priming = _execute_plan(args, loaded, plan)
    if priming_status is AggregateStatus.FAILED:
        print(
            "Benchmark priming failed; warm iterations were not run.",
            file=sys.stderr,
        )
        return 1
    warm_runs: list[BenchmarkRun] = []
    for index in range(1, args.iterations + 1):
        args.results_dir = benchmark_root / f"warm-{index}"
        _, summary = _execute_plan(args, loaded, plan)
        warm_runs.append(
            BenchmarkRun(
                index=index,
                status=summary.status,
                wall_seconds=summary.wall_seconds,
                critical_path_seconds=summary.critical_path_seconds,
                cache_hit_ratio=summary.cache_hit_ratio,
                cache_hit_groups=summary.cache_hit_groups,
            )
        )
    wall_times = [run.wall_seconds for run in warm_runs]
    hit_ratio = sum(run.cache_hit_ratio for run in warm_runs) / len(warm_runs)
    target_p95 = 120.0 if selected_tier in {Tier.QUICK, Tier.AFFECTED} else 300.0
    p95 = percentile(wall_times, 0.95)
    evidence = BenchmarkEvidence(
        tier=selected_tier,
        plan_hash=plan.plan_hash,
        warm_run_count=len(warm_runs),
        planning_seconds=planning_seconds,
        priming_wall_seconds=priming.wall_seconds,
        warm_runs=tuple(warm_runs),
        warm_p50_seconds=percentile(wall_times, 0.5),
        warm_p95_seconds=p95,
        cache_hit_ratio=hit_ratio,
        target_p95_seconds=target_p95,
        target_planning_seconds=5.0,
        targets_met=(
            p95 <= target_p95
            and priming.wall_seconds <= target_p95
            and planning_seconds <= 5.0
            and hit_ratio == 1.0
            and all(run.status is not AggregateStatus.FAILED for run in warm_runs)
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_json_text(evidence) + "\n", encoding="utf-8")
    if args.json:
        print(_json_text(evidence))
    else:
        print(
            f"Benchmark {selected_tier.value}: P50={evidence.warm_p50_seconds:.3f}s "
            f"P95={evidence.warm_p95_seconds:.3f}s hits={evidence.cache_hit_ratio:.1%}"
        )
    return 0 if evidence.targets_met else 1


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        actual = ".".join(str(part) for part in sys.version_info[:3])
        print(
            f"Python 3.13 or newer is required; current interpreter is {actual}",
            file=sys.stderr,
        )
        return 2
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "validate": _command_validate,
        "explain": _command_explain,
        "plan": _command_plan,
        "verify": _command_verify,
        "run": _command_run,
        "run-group": _command_run_group,
        "aggregate": _command_aggregate,
        "docker-build": _command_docker_build,
        "warm-preflight": _command_warm_preflight,
        "topology-stamp": _command_topology_stamp,
        "benchmark": _command_benchmark,
    }
    try:
        return commands[args.command](args)
    except (
        OSError,
        ValueError,
        KeyError,
        ChangeDiscoveryError,
        TopologyCollectionError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
