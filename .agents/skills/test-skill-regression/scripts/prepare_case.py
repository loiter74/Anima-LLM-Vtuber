#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from compare_runs import case_baseline, load_case, preflight_invariants


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预检固定用例并创建相互隔离的运行副本。")
    parser.add_argument("--case", required=True, type=Path, help="固定用例 JSON")
    parser.add_argument("--output-root", type=Path, help="隔离副本根目录；默认使用系统临时目录")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    case = load_case(args.case)
    baseline = case_baseline(args.case, case)
    preflight_passed, checks = preflight_invariants(case, baseline)
    if not preflight_passed:
        print(
            "语义预检失败：" + json.dumps(checks, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 1

    if args.output_root:
        output_root = args.output_root.resolve()
        if output_root.exists():
            raise ValueError(f"隔离副本根目录已存在：{output_root}")
        output_root.mkdir(parents=True)
    else:
        output_root = Path(tempfile.mkdtemp(prefix=f"anima-skill-{case['id']}-"))

    run_roots: list[Path] = []
    for index in range(1, case["run_count"] + 1):
        run_root = output_root / f"run-{index}"
        shutil.copytree(baseline, run_root)
        run_roots.append(run_root)

    marker = {
        "schema_version": 1,
        "case_id": case["id"],
        "run_count": case["run_count"],
    }
    (output_root / ".skill-regression.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": case["id"],
                "task": case["task"],
                "preflight_passed": True,
                "output_root": str(output_root),
                "run_roots": [str(root) for root in run_roots],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
