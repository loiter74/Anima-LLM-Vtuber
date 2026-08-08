"""One-command report for the hermetic typed Minecraft workflow demo."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from .scenario import build_demo_scenario, run_demo_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="minecraft-demo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo")
    demo.add_argument("--output", type=Path, default=Path("artifacts/minecraft-demo"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run_demo_workflow(build_demo_scenario()))
    data = report.summary()
    (output / "report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Typed Minecraft fallback workflow", ""]
    for index, step in enumerate(report.steps, start=1):
        suffix = (
            f"Failure detected ({step.error_code}); Recovered, run continued"
            if step.recovered
            else "completed"
        )
        lines.append(f"{index}. `{step.capability}` — {suffix}")
    (output / "trace.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if report.completed else 1
