"""Survival iron-run benchmark — summarizes mock and real-server results."""

from __future__ import annotations

from typing import Any

from .models import RunReport


def summarize_run(report: RunReport) -> dict[str, Any]:
    """Create a compact summary of a survival run.

    Returns a dict suitable for logging, storage, or LLM consumption.
    """
    summary = report.summary()
    summary["iron_gear_achieved"] = _check_iron_gear(report.final_inventory)
    summary["phase_durations_ms"] = [
        {"phase": pr.phase.value, "elapsed_ms": round(pr.elapsed_ms, 1)}
        for pr in report.phase_results
    ]
    summary["failure_categories"] = [
        pr.failure_category.value for pr in report.phase_results if pr.failure_category
    ]
    return summary


def _check_iron_gear(inventory: dict[str, int]) -> dict[str, bool]:
    """Check which iron gear items are present."""
    return {
        "iron_pickaxe": inventory.get("iron_pickaxe", 0) >= 1,
        "iron_sword": inventory.get("iron_sword", 0) >= 1,
        "iron_chestplate": inventory.get("iron_chestplate", 0) >= 1,
    }


def render_markdown_report(report: RunReport) -> str:
    """Render a human-readable markdown report of a survival run."""
    lines = ["# Survival Iron Run Report", ""]

    status = "COMPLETED" if report.completed else "INCOMPLETE"
    lines.append(f"**Status:** {status}")
    lines.append(f"**Duration:** {report.elapsed_seconds:.0f}s")
    lines.append(f"**Deaths:** {report.deaths}")
    lines.append(f"**Phases attempted:** {len(report.phase_results)}")
    lines.append("")

    # Phase table
    lines.append("## Phase Progress")
    lines.append("")
    lines.append("| Phase | Status | Actions | Failure |")
    lines.append("|-------|--------|---------|---------|")
    for pr in report.phase_results:
        s = "PASS" if pr.success else "FAIL"
        fail = pr.failure_category.value if pr.failure_category else ""
        lines.append(
            f"| {pr.phase.value} | {s} | {pr.actions_succeeded}/{pr.actions_attempted} | {fail} |"
        )
    lines.append("")

    # Final inventory
    lines.append("## Final Inventory")
    lines.append("")
    if report.final_inventory:
        for item, count in sorted(report.final_inventory.items()):
            lines.append(f"- {item}: {count}")
    else:
        lines.append("(no data)")
    lines.append("")

    # Iron gear check
    gear = _check_iron_gear(report.final_inventory)
    lines.append("## Iron Gear Status")
    lines.append("")
    for item, present in gear.items():
        mark = "ACHIEVED" if present else "MISSING"
        lines.append(f"- {item}: {mark}")

    return "\n".join(lines)


def compare_runs(reports: list[RunReport]) -> dict[str, Any]:
    """Compare multiple survival runs for benchmarking."""
    if not reports:
        return {"runs": 0}

    completed = sum(1 for r in reports if r.completed)
    avg_duration = sum(r.elapsed_seconds for r in reports) / len(reports)
    avg_deaths = sum(r.deaths for r in reports) / len(reports)

    # Phase success rates
    phase_stats: dict[str, dict[str, int]] = {}
    for pr_list in [r.phase_results for r in reports]:
        for pr in pr_list:
            key = pr.phase.value
            if key not in phase_stats:
                phase_stats[key] = {"attempts": 0, "successes": 0}
            phase_stats[key]["attempts"] += 1
            if pr.success:
                phase_stats[key]["successes"] += 1

    return {
        "runs": len(reports),
        "completed": completed,
        "completion_rate": completed / len(reports),
        "avg_duration_seconds": round(avg_duration, 1),
        "avg_deaths": round(avg_deaths, 2),
        "phase_success_rates": {
            k: round(v["successes"] / v["attempts"], 2) if v["attempts"] > 0 else 0
            for k, v in phase_stats.items()
        },
    }
