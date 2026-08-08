"""The demo uses the typed workflow and has no production bridge bypass."""

from __future__ import annotations

import json

from animetta.tools.minecraft.demo.cli import main
from animetta.tools.minecraft.demo.scenario import (
    build_demo_scenario,
    count_recoveries,
    run_demo_workflow,
)


async def test_typed_demo_completes_and_recovers_three_named_failures() -> None:
    report = await run_demo_workflow(build_demo_scenario())

    assert report.completed is True
    assert report.final_inventory["iron_ingot"] >= 1
    assert count_recoveries(report.steps) == 3
    assert {step.error_code for step in report.steps if step.recovered} == {
        "PARTIAL_COLLECT",
        "NO_CRAFTING_TABLE",
        "SMELT_NO_FURNACE",
    }


def test_cli_writes_report_and_trace(tmp_path) -> None:
    output = tmp_path / "demo"
    assert main(["demo", "--output", str(output)]) == 0
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    trace = (output / "trace.md").read_text(encoding="utf-8")

    assert report["completed"] is True
    assert report["recoveries_triggered"] == 3
    assert "Failure detected" in trace
    assert "Recovered, run continued" in trace
