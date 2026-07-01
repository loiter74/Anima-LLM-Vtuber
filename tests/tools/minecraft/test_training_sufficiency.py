"""T10: 训练充分判据 + 阶段切换 (mc-bot-voyager-learning)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.autonomous.loop import AutonomousLoop
from animetta.tools.minecraft.autonomous.training import TrainingTracker

# ── TrainingTracker 纯逻辑 ────────────────────────────────────────────────────


def test_coverage_criterion_triggers():
    """判据①：技术树全覆盖 → 充分。"""
    t = TrainingTracker(min_recent_samples=999, min_items_discovered=999)  # 关闭②③
    t.update_discovered({item: 1 for item in t.tech_tree_targets})
    ok, reason = t.sufficiency()
    assert ok and reason == "tech_tree_coverage"
    assert t.tech_tree_coverage() == 1.0


def test_coverage_partial_below_threshold_not_sufficient():
    t = TrainingTracker(min_coverage=0.8, min_recent_samples=999, min_items_discovered=999)
    t.update_discovered({"wooden_pickaxe": 1, "crafting_table": 1})  # 2/6 ≈ 0.33 < 0.8
    assert not t.is_sufficient()


def test_recent_rate_criterion_triggers():
    """判据②：窗口内成功率 ≥ 70% 且样本数 ≥ min_recent_samples。"""
    t = TrainingTracker(
        min_coverage=2.0, min_recent_samples=5, min_recent_rate=0.7, min_items_discovered=999
    )
    for _ in range(4):
        t.record_task_result(True)
    assert not t.is_sufficient()  # 样本不足（4 < 5）
    t.record_task_result(True)
    ok, reason = t.sufficiency()
    assert ok and reason == "recent_success_rate"


def test_recent_rate_with_some_failures_still_passes():
    t = TrainingTracker(
        min_coverage=2.0, min_recent_samples=10, min_recent_rate=0.7, min_items_discovered=999
    )
    # 7 通过 / 3 失败 = 0.7 ≥ 0.7，样本 10 ≥ 10
    for _ in range(7):
        t.record_task_result(True)
    for _ in range(3):
        t.record_task_result(False)
    assert t.recent_success_rate() == 0.7
    assert t.is_sufficient()


def test_items_criterion_triggers():
    """判据③：unique 物品发现数 ≥ 阈值。"""
    t = TrainingTracker(min_coverage=2.0, min_recent_samples=999, min_items_discovered=10)
    t.update_discovered({f"item_{i}": 1 for i in range(9)})
    assert not t.is_sufficient()
    t.update_discovered({"item_10": 1})
    ok, reason = t.sufficiency()
    assert ok and reason == "items_discovered"


def test_not_sufficient_when_empty():
    t = TrainingTracker()
    assert not t.is_sufficient()
    assert t.items_discovered_count == 0
    assert t.recent_success_rate() == 0.0


def test_summary_shape():
    t = TrainingTracker()
    t.update_discovered({"oak_log": 2, "stone": 1})
    t.record_task_result(True)
    s = t.summary()
    assert s["items_discovered"] == 2
    assert s["recent_samples"] == 1
    assert "tech_tree_coverage" in s and "is_sufficient" in s


# ── AutonomousLoop 集成（learn→live 自动提升）────────────────────────────────


def test_loop_promotes_learn_to_live_when_sufficient():
    bridge = AsyncMock()
    tracker = TrainingTracker(min_coverage=2.0, min_recent_samples=999, min_items_discovered=3)
    loop = AutonomousLoop(bridge, training_tracker=tracker)
    loop.set_voyager_mode("learn")
    tracker.update_discovered({"a": 1, "b": 1, "c": 1})

    loop._check_training_sufficient()

    assert loop.voyager_mode == "live"


def test_loop_does_not_switch_when_not_learn():
    """非 learn 模式（fallback/live）不触发自动提升。"""
    bridge = AsyncMock()
    tracker = TrainingTracker(min_items_discovered=1)
    loop = AutonomousLoop(bridge, training_tracker=tracker)
    loop.set_voyager_mode("fallback")
    tracker.update_discovered({"a": 1})

    loop._check_training_sufficient()

    assert loop.voyager_mode == "fallback"


def test_loop_does_not_switch_when_not_sufficient():
    bridge = AsyncMock()
    tracker = TrainingTracker(min_coverage=2.0, min_recent_samples=999, min_items_discovered=999)
    loop = AutonomousLoop(bridge, training_tracker=tracker)
    loop.set_voyager_mode("learn")
    tracker.update_discovered({"only_one": 1})

    loop._check_training_sufficient()

    assert loop.voyager_mode == "learn"  # 未达标，保持 learn
