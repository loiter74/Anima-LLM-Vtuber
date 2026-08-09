#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast


class FileRecord(TypedDict):
    sha256: str
    size: int


class Delta(TypedDict):
    added: list[str]
    modified: list[str]
    deleted: list[str]


class Invariant(TypedDict):
    path: str
    contains: list[str]


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
        if (
            not isinstance(invariant, dict)
            or not isinstance(invariant.get("path"), str)
            or not invariant["path"]
            or not isinstance(invariant.get("contains"), list)
            or not invariant["contains"]
            or not all(isinstance(fragment, str) and fragment for fragment in invariant["contains"])
        ):
            raise ValueError(f"固定用例 invariant 无效：{path}")
    return cast(RegressionCase, payload)


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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按固定用例比较多次 Skill 运行清单。")
    parser.add_argument("--case", required=True, type=Path, help="固定用例 JSON")
    parser.add_argument("--baseline", required=True, type=Path, help="基线清单")
    parser.add_argument("runs", nargs="+", type=Path, help="每次运行后的清单")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    case = load_case(args.case)
    if len(args.runs) != case["run_count"]:
        raise ValueError(
            f"固定用例要求 {case['run_count']} 次运行，实际收到 {len(args.runs)} 个清单"
        )

    baseline = load_manifest(args.baseline)
    run_files = [load_manifest(path) for path in args.runs]
    deltas = [delta(baseline, files) for files in run_files]

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

    result = {
        "schema_version": 1,
        "case_id": case["id"],
        "skill": case["skill"],
        "baseline_fixture": case["baseline"],
        "path_consistent": path_consistent,
        "content_identical_on_affected_paths": content_identical,
        "content_identity_required": case["require_content_identical"],
        "boundary_consistent": boundary_consistent,
        "semantic_invariants": case["invariants"],
        "semantic_invariants_require_manual_check": True,
        "runs": [
            {"manifest": path.name, **item} for path, item in zip(args.runs, deltas, strict=True)
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    failed = not path_consistent or not boundary_consistent
    if case["require_content_identical"]:
        failed = failed or not content_identical
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
