#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import NotRequired, TypedDict, cast

from snapshot_tree import DEFAULT_EXCLUDES, build_manifest


class FileRecord(TypedDict):
    sha256: str
    size: int


class Delta(TypedDict):
    added: list[str]
    modified: list[str]
    deleted: list[str]


class Invariant(TypedDict):
    path: str
    contains: NotRequired[list[str]]
    not_contains: NotRequired[list[str]]


class RegressionCase(TypedDict):
    schema_version: int
    id: str
    skill: str
    task: str
    baseline: str
    run_count: int
    allowed_paths: list[str]
    require_content_identical: bool
    invariants: list[Invariant]


def load_manifest(path: Path) -> dict[str, FileRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("files"), dict):
        raise ValueError(f"清单无效：{path}")
    return cast(dict[str, FileRecord], payload["files"])


def load_case(path: Path) -> RegressionCase:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required_strings = ("id", "skill", "task", "baseline")
    if payload.get("schema_version") != 1 or any(
        not isinstance(payload.get(key), str) or not payload[key] for key in required_strings
    ):
        raise ValueError(f"固定用例基础字段无效：{path}")
    if not isinstance(payload.get("run_count"), int) or payload["run_count"] < 2:
        raise ValueError(f"固定用例 run_count 必须至少为 2：{path}")
    if not isinstance(payload.get("require_content_identical"), bool):
        raise ValueError(f"固定用例 require_content_identical 无效：{path}")
    allowed_paths = payload.get("allowed_paths")
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or not all(isinstance(item, str) and item for item in allowed_paths)
    ):
        raise ValueError(f"固定用例 allowed_paths 无效：{path}")
    invariants = payload.get("invariants")
    if not isinstance(invariants, list) or not invariants:
        raise ValueError(f"固定用例 invariants 不得为空：{path}")
    for invariant in invariants:
        if not isinstance(invariant, dict) or not isinstance(invariant.get("path"), str):
            raise ValueError(f"固定用例 invariant 无效：{path}")
        contains = invariant.get("contains", [])
        not_contains = invariant.get("not_contains", [])
        fragments_valid = all(
            isinstance(fragments, list)
            and all(isinstance(fragment, str) and fragment for fragment in fragments)
            for fragments in (contains, not_contains)
        )
        if not invariant["path"] or not fragments_valid or not (contains or not_contains):
            raise ValueError(f"固定用例 invariant 无效：{path}")
    return cast(RegressionCase, payload)


def case_baseline(case_path: Path, case: RegressionCase) -> Path:
    baseline = (case_path.parent / case["baseline"]).resolve(strict=True)
    if not baseline.is_dir():
        raise ValueError(f"固定用例基线不是目录：{baseline}")
    return baseline


def read_invariant_text(root: Path, relative_path: str) -> tuple[str | None, str | None]:
    resolved_root = root.resolve(strict=True)
    relative = PurePosixPath(relative_path)
    target = (resolved_root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(resolved_root) or not target.is_file():
        return None, "目标文件不存在或越出运行目录"
    try:
        return target.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return None, "目标文件不是 UTF-8 文本"


def preflight_invariants(
    case: RegressionCase, baseline: Path
) -> tuple[bool, list[dict[str, object]]]:
    checks: list[dict[str, object]] = []
    for invariant in case["invariants"]:
        _, error = read_invariant_text(baseline, invariant["path"])
        forbidden = invariant.get("not_contains", [])
        contradictions = [
            fragment
            for fragment in forbidden
            if any(fragment in required for required in invariant.get("contains", []))
        ]
        task_conflicts = [fragment for fragment in forbidden if fragment in case["task"]]
        checks.append(
            {
                "path": invariant["path"],
                "passed": error is None and not contradictions and not task_conflicts,
                "error": error,
                "constraint_conflicts": contradictions,
                "task_conflicts": task_conflicts,
            }
        )
    return all(bool(check["passed"]) for check in checks), checks


def evaluate_invariants(case: RegressionCase, root: Path) -> tuple[bool, list[dict[str, object]]]:
    checks: list[dict[str, object]] = []
    for invariant in case["invariants"]:
        content, error = read_invariant_text(root, invariant["path"])
        if error or content is None:
            checks.append({"path": invariant["path"], "passed": False, "error": error})
            continue
        missing = [
            fragment for fragment in invariant.get("contains", []) if fragment not in content
        ]
        forbidden = [
            fragment for fragment in invariant.get("not_contains", []) if fragment in content
        ]
        checks.append(
            {
                "path": invariant["path"],
                "passed": not missing and not forbidden,
                "missing_contains": missing,
                "present_not_contains": forbidden,
            }
        )
    return all(bool(check["passed"]) for check in checks), checks


def delta(baseline: dict[str, FileRecord], current: dict[str, FileRecord]) -> Delta:
    baseline_paths = set(baseline)
    current_paths = set(current)
    return {
        "added": sorted(current_paths - baseline_paths),
        "modified": sorted(
            path
            for path in baseline_paths & current_paths
            if baseline[path]["sha256"] != current[path]["sha256"]
        ),
        "deleted": sorted(baseline_paths - current_paths),
    }


def changed_paths(change: Delta) -> tuple[str, ...]:
    return tuple(change["added"] + change["modified"] + change["deleted"])


def path_is_allowed(path: str, patterns: Sequence[str]) -> bool:
    return any(PurePosixPath(path).match(pattern) for pattern in patterns)


def files_for_root(root: Path) -> dict[str, FileRecord]:
    output_placeholder = root / ".skill-regression-manifest.json"
    payload = build_manifest(root, output_placeholder, set(DEFAULT_EXCLUDES))
    return cast(dict[str, FileRecord], payload["files"])


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按固定用例比较多次 Skill 运行。")
    parser.add_argument("--case", required=True, type=Path, help="固定用例 JSON")
    parser.add_argument("--prepared-root", type=Path, help="prepare_case.py 创建的隔离运行根目录")
    parser.add_argument("--baseline", type=Path, help="兼容模式：基线清单")
    parser.add_argument("runs", nargs="*", type=Path, help="兼容模式：每次运行后的清单")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    case = load_case(args.case)
    run_roots: list[Path] = []

    if args.prepared_root:
        if args.baseline or args.runs:
            raise ValueError("--prepared-root 不得与清单参数混用")
        marker_path = args.prepared_root / ".skill-regression.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("case_id") != case["id"] or marker.get("run_count") != case["run_count"]:
            raise ValueError(f"隔离运行目录与固定用例不匹配：{args.prepared_root}")
        baseline = files_for_root(case_baseline(args.case, case))
        run_roots = [
            args.prepared_root / f"run-{index}" for index in range(1, case["run_count"] + 1)
        ]
        run_files = [files_for_root(root) for root in run_roots]
        run_labels = [root.name for root in run_roots]
    else:
        if args.baseline is None:
            raise ValueError("必须提供 --prepared-root 或 --baseline")
        if len(args.runs) != case["run_count"]:
            raise ValueError(
                f"固定用例要求 {case['run_count']} 次运行，实际收到 {len(args.runs)} 个清单"
            )
        baseline = load_manifest(args.baseline)
        run_files = [load_manifest(path) for path in args.runs]
        run_labels = [path.name for path in args.runs]

    deltas = [delta(baseline, files) for files in run_files]
    changes_observed = all(bool(changed_paths(item)) for item in deltas)
    path_consistent = all(changed_paths(item) == changed_paths(deltas[0]) for item in deltas[1:])
    affected = sorted(set(deltas[0]["added"] + deltas[0]["modified"])) if path_consistent else []
    content_identical = path_consistent and all(
        all(
            path in files and files[path]["sha256"] == run_files[0][path]["sha256"]
            for path in affected
        )
        for files in run_files[1:]
    )
    boundary_consistent = all(
        path_is_allowed(path, case["allowed_paths"])
        for item in deltas
        for path in changed_paths(item)
    )

    invariant_results: list[dict[str, object]] = []
    semantic_passed: bool | None = None
    if run_roots:
        for root in run_roots:
            passed, checks = evaluate_invariants(case, root)
            invariant_results.append({"run": root.name, "passed": passed, "checks": checks})
        semantic_passed = all(bool(item["passed"]) for item in invariant_results)

    result = {
        "schema_version": 1,
        "case_id": case["id"],
        "skill": case["skill"],
        "baseline_fixture": case["baseline"],
        "changes_observed": changes_observed,
        "path_consistent": path_consistent,
        "content_identical_on_affected_paths": content_identical,
        "content_identity_required": case["require_content_identical"],
        "boundary_consistent": boundary_consistent,
        "semantic_invariants": case["invariants"],
        "semantic_invariants_passed": semantic_passed,
        "semantic_invariants_require_manual_check": not run_roots,
        "invariant_results": invariant_results,
        "runs": [
            {"manifest": label, **item} for label, item in zip(run_labels, deltas, strict=True)
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    failed = (
        not changes_observed
        or not path_consistent
        or not boundary_consistent
        or semantic_passed is False
    )
    if case["require_content_identical"]:
        failed = failed or not content_identical
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
