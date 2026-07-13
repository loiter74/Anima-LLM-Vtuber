from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .aggregate import aggregate_results
from .change_sources import ChangeDiscoveryError, discover_range, discover_worktree, from_paths
from .evidence import read_plan, read_results, write_plan, write_summary
from .executor import run_group, write_result
from .manifest import LoadedCatalog, load_catalog
from .models import (
    AggregateStatus,
    AggregateSummary,
    ChangeSet,
    ResultStatus,
    Runner,
    Tier,
    VerificationPlan,
)
from .planner import matching_components, plan_verification

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
    verify.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run")
    _add_catalog_arguments(run)
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--results-dir", type=Path)
    run.add_argument("--json", action="store_true")

    run_one = subparsers.add_parser("run-group")
    run_one.add_argument("group_id")
    _add_catalog_arguments(run_one)
    run_one.add_argument("--plan", type=Path, required=True)
    run_one.add_argument("--output", type=Path)
    run_one.add_argument("--json", action="store_true")

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--plan", type=Path, required=True)
    aggregate.add_argument("--results-dir", type=Path, required=True)
    aggregate.add_argument("--output", type=Path)
    aggregate.add_argument("--json", action="store_true")
    return parser


def _json_text(model) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False)


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
                f"{json.dumps(groups, ensure_ascii=False, separators=(',', ':'))}\n"
            )
            handle.write(f"has_{environment}={'true' if groups else 'false'}\n")
        handle.write(f"plan_hash={plan.plan_hash}\n")


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
        print(json.dumps(payload, indent=2, ensure_ascii=False))
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
        print(json.dumps(payload, indent=2, ensure_ascii=False))
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


def _execute_plan(
    args: argparse.Namespace,
    loaded: LoadedCatalog,
    plan: VerificationPlan,
) -> tuple[AggregateStatus, AggregateSummary]:
    results_dir = _results_directory(args, plan)
    _invalidate_plan_evidence(results_dir, plan)
    results = []
    for group in plan.groups:
        result = run_group(
            loaded,
            group.id,
            plan_hash=plan.plan_hash,
            repo_root=args.repo_root,
        )
        write_result(result, results_dir / f"{group.id}.json")
        results.append(result)
    summary = aggregate_results(plan, results)
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
    plan = plan_verification(
        loaded,
        changes,
        Tier(args.tier),
        discovery_failure=discovery_failure,
    )
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
    selected = {group.id for group in plan.groups}
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
    result = run_group(
        loaded,
        args.group_id,
        plan_hash=plan.plan_hash,
        repo_root=args.repo_root,
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
    }
    try:
        return commands[args.command](args)
    except (OSError, ValueError, KeyError, ChangeDiscoveryError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
