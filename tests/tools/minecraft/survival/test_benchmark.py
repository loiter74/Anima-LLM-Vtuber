"""Tests for survival_benchmark.py — run summaries and markdown reports."""

from animetta.tools.minecraft.survival_benchmark import (
    compare_runs,
    render_markdown_report,
    summarize_run,
)
from animetta.tools.minecraft.survival_models import (
    FailureCategory,
    PhaseResult,
    RunReport,
    SurvivalPhase,
)


def _make_report(completed: bool = True, phases: int = 9) -> RunReport:
    r = RunReport(start_time=100.0, end_time=200.0, completed=completed)
    r.final_inventory = {"iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1}
    for i in range(min(phases, len(SurvivalPhase) - 1)):
        phase = list(SurvivalPhase)[i]
        pr = PhaseResult(phase=phase, success=True, actions_attempted=1, actions_succeeded=1)
        pr.elapsed_ms = 5000.0
        r.phase_results.append(pr)
    return r


class TestSummarizeRun:
    def test_basic_summary(self):
        r = _make_report()
        s = summarize_run(r)
        assert s["completed"] is True
        assert s["elapsed_seconds"] == 100.0
        assert "iron_gear_achieved" in s
        assert s["iron_gear_achieved"]["iron_pickaxe"] is True

    def test_incomplete_summary(self):
        r = _make_report(completed=False, phases=3)
        r.phase_results[-1] = PhaseResult(
            phase=r.phase_results[-1].phase,
            success=False,
            failure_category=FailureCategory.ACTION_FAILED,
        )
        s = summarize_run(r)
        assert s["completed"] is False
        assert len(s["failure_categories"]) == 1

    def test_phase_durations(self):
        r = _make_report(phases=3)
        s = summarize_run(r)
        assert len(s["phase_durations_ms"]) == 3
        assert all(d["elapsed_ms"] == 5000.0 for d in s["phase_durations_ms"])


class TestRenderMarkdownReport:
    def test_contains_headers(self):
        r = _make_report()
        md = render_markdown_report(r)
        assert "# Survival Iron Run Report" in md
        assert "## Phase Progress" in md
        assert "## Final Inventory" in md
        assert "## Iron Gear Status" in md

    def test_completed_report(self):
        r = _make_report()
        md = render_markdown_report(r)
        assert "COMPLETED" in md
        assert "100s" in md

    def test_incomplete_report(self):
        r = _make_report(completed=False, phases=3)
        md = render_markdown_report(r)
        assert "INCOMPLETE" in md

    def test_failure_in_table(self):
        r = _make_report(phases=3)
        r.phase_results[-1] = PhaseResult(
            phase=r.phase_results[-1].phase,
            success=False,
            failure_category=FailureCategory.SAFETY_PAUSE,
            failure_message="Health low",
        )
        md = render_markdown_report(r)
        assert "FAIL" in md
        assert "safety_pause" in md


class TestCompareRuns:
    def test_empty_runs(self):
        result = compare_runs([])
        assert result["runs"] == 0

    def test_single_run(self):
        r = _make_report()
        result = compare_runs([r])
        assert result["runs"] == 1
        assert result["completed"] == 1
        assert result["completion_rate"] == 1.0

    def test_multiple_runs(self):
        r1 = _make_report(completed=True)
        r2 = _make_report(completed=False)
        result = compare_runs([r1, r2])
        assert result["runs"] == 2
        assert result["completed"] == 1
        assert result["completion_rate"] == 0.5
        assert result["avg_duration_seconds"] == 100.0

    def test_phase_success_rates(self):
        r = _make_report(phases=3)
        result = compare_runs([r])
        rates = result["phase_success_rates"]
        assert len(rates) == 3
        for phase_name, rate in rates.items():
            assert rate == 1.0
