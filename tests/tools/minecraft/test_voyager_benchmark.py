"""T14: benchmark Voyager 论文指标 (mc-bot-voyager-learning)."""

from __future__ import annotations

from animetta.tools.minecraft.benchmark.criteria import (
    TECH_TREE_KEY_ITEMS,
    _check_voyager_paper_criteria,
    compute_tech_tree_coverage,
    evaluate_voyager_metrics,
)
from animetta.tools.minecraft.benchmark.models import BenchmarkMetrics
from animetta.tools.minecraft.benchmark.report import generate_benchmark_report


def test_metrics_new_fields_default():
    """新论文指标字段有默认值（向后兼容）。"""
    m = BenchmarkMetrics()
    assert m.tech_tree_coverage == 0.0
    assert m.avg_iterations_per_task == 0.0
    assert m.total_tokens == 0


def test_tech_tree_coverage():
    """覆盖率 = key 节点在 inventory 出现比例。"""
    # 6 个 key 节点，达成 3 个 → 0.5
    inv = {"wooden_pickaxe": 1, "stone_pickaxe": 1, "crafting_table": 1, "dirt": 64}
    assert compute_tech_tree_coverage(inv) == 3 / len(TECH_TREE_KEY_ITEMS)

    # 全部达成 → 1.0
    full = {item: 1 for item in TECH_TREE_KEY_ITEMS}
    assert compute_tech_tree_coverage(full) == 1.0

    # 空 / 无 key → 0.0
    assert compute_tech_tree_coverage({}) == 0.0
    assert compute_tech_tree_coverage({"dirt": 64}) == 0.0


def test_voyager_paper_criteria_pass():
    m = BenchmarkMetrics(tech_tree_coverage=0.9, avg_iterations_per_task=2.5, total_tokens=5000)
    assert _check_voyager_paper_criteria(m, {"min_tech_tree_coverage": 0.8}) is True


def test_voyager_paper_criteria_fail_low_coverage():
    m = BenchmarkMetrics(tech_tree_coverage=0.5, avg_iterations_per_task=2.0, total_tokens=100)
    assert _check_voyager_paper_criteria(m, {}) is False  # 默认阈值 0.8


def test_voyager_paper_criteria_fail_high_iters():
    m = BenchmarkMetrics(tech_tree_coverage=1.0, avg_iterations_per_task=5.0, total_tokens=100)
    assert _check_voyager_paper_criteria(m, {"max_avg_iterations": 4}) is False


def test_voyager_paper_criteria_fail_tokens():
    m = BenchmarkMetrics(tech_tree_coverage=1.0, avg_iterations_per_task=1.0, total_tokens=999999)
    assert _check_voyager_paper_criteria(m, {"max_total_tokens": 100000}) is False


def test_evaluate_voyager_metrics_mapping():
    m = BenchmarkMetrics(
        unique_items_collected=12,
        tech_tree_coverage=0.83,
        task_success_rate=0.7,
        avg_iterations_per_task=2.1,
        total_tokens=4200,
        skills_created=5,
        skills_reused=3,
    )
    out = evaluate_voyager_metrics(m)
    assert out["unique_items_discovered"] == 12
    assert out["tech_tree_coverage"] == 0.83
    assert out["avg_iterations_per_task"] == 2.1
    assert out["total_tokens"] == 4200


def test_report_contains_paper_columns():
    """生成的 markdown 报告含新论文指标列。"""
    m = BenchmarkMetrics(
        completed=True,
        elapsed_seconds=120.0,
        unique_items_collected=8,
        distance_traveled=400.0,
        deaths=0,
        skills_created=3,
        task_success_rate=0.75,
        tech_tree_coverage=0.83,
        avg_iterations_per_task=2.4,
        total_tokens=1500,
    )
    report = generate_benchmark_report({"iron_survival": {"full-voyager": m}})
    assert "TechCov" in report
    assert "AvgIter" in report
    assert "Tokens" in report
    assert "83%" in report
    assert "1500" in report
