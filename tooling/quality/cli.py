from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .aggregate import aggregate_results
from .benchmark import BenchmarkEvidence, BenchmarkRun, percentile
from .cache import ResultCache, artifact_digest
from .change_sources import ChangeDiscoveryError, discover_range, discover_worktree, from_paths
from .docker_plan import compose_identity, fingerprint_docker_scopes
from .evidence import read_plan, read_results, write_plan, write_summary
from .executor import run_group, write_result
from .fingerprint import FingerprintContext
from .manifest import LoadedCatalog, load_catalog
from .models import (
    AggregateStatus,
    AggregateSummary,
    CacheMode,
    ChangeSet,
    PlannedGroup,
    ResultStatus,
    Runner,
    SchedulerPolicy,
    Tier,
    TrustScope,
    VerificationPlan,
)
from .planner import matching_components, plan_verification
from .scheduler import run_schedule
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


def _execute_planned_group(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
    plan: VerificationPlan,
    group: PlannedGroup,
    cancellation: threading.Event,
    *,
    cache: ResultCache | None,
    cache_mode: CacheMode,
    trust_scope: TrustScope,
):
    miss_reason = "cache-off"
    if cache is not None and cache_mode in {CacheMode.READ, CacheMode.READ_WRITE}:
        lookup = cache.lookup(
            group,
            plan_hash=plan.plan_hash,
            manifest_hash=plan.manifest_hash,
            trust_scope=trust_scope,
        )
        if lookup.hit:
            assert lookup.result is not None
            return lookup.result
        miss_reason = lookup.reason
    result = run_group(
        loaded,
        group.id,
        plan_hash=plan.plan_hash,
        repo_root=args.repo_root,
        cancellation_event=cancellation,
    )
    repo_root = Path(args.repo_root).resolve()
    result = result.model_copy(
        update={
            "input_fingerprint": group.input_fingerprint,
            "trust_scope": trust_scope,
            "cache_reason": miss_reason,
            "artifact_digests": _artifact_digest_map(repo_root, result.artifacts),
        }
    )
    if cache is not None and cache_mode is CacheMode.READ_WRITE:
        write = cache.store(group, result, trust_scope)
        result = result.model_copy(
            update={"cache_reason": f"miss:{miss_reason};write:{write.reason}"}
        )
    return result


def _execute_plan(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
    plan: VerificationPlan,
) -> tuple[AggregateStatus, AggregateSummary]:
    results_dir = _results_directory(args, plan)
    _invalidate_plan_evidence(results_dir, plan)
    cache_mode = _resolved_cache_mode(args, plan)
    trust_scope = _resolved_trust_scope(args, plan)
    cache = None if cache_mode is CacheMode.OFF else ResultCache(_cache_root(args), args.repo_root)
    cancellation = threading.Event()
    policy = plan.scheduler
    if getattr(args, "sequential", False) or getattr(args, "shadow_sequential", False):
        policy = SchedulerPolicy(
            max_workers=1,
            max_weight=plan.scheduler.max_weight,
            max_heavy=1,
            max_exclusive=1,
        )

    def execute(group: PlannedGroup, event: threading.Event):
        return _execute_planned_group(
            args,
            loaded,
            plan,
            group,
            event,
            cache=cache,
            cache_mode=cache_mode,
            trust_scope=trust_scope,
        )

    outcome = run_schedule(
        plan.groups,
        policy,
        execute,
        cancellation_event=cancellation,
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
    )
    for result in outcome.results:
        write_result(result, results_dir / f"{result.group_id}.json")
    summary = aggregate_results(plan, outcome.results).model_copy(
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
    output.unlink(missing_ok=True)
    cache_mode = _resolved_cache_mode(args, plan)
    trust_scope = _resolved_trust_scope(args, plan)
    cache = None if cache_mode is CacheMode.OFF else ResultCache(_cache_root(args), args.repo_root)
    result = _execute_planned_group(
        args,
        loaded,
        plan,
        selected[args.group_id],
        threading.Event(),
        cache=cache,
        cache_mode=cache_mode,
        trust_scope=trust_scope,
    )
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
        "qwen-tts": "QWEN_TTS_BUILD_FINGERPRINT",
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
    target_p95 = 120.0 if selected_tier is Tier.QUICK else 300.0
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
