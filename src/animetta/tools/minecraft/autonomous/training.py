"""训练充分判据 + 阶段切换（mc-bot-voyager-learning T10）。

Voyager 学习期跑够了就切直播期。判据三选一达标即可切（学习期仍可后台继续攒技能）：
  ① 技术树覆盖率：木/石/铁/钻石工具 + 基础建造 的 verified 技能/物品覆盖 ≥ 80%
  ② 近期成功率：最近 N 个任务自我验证通过率 ≥ 70%（需攒满窗口样本，避免早期误判）
  ③ 物品发现数：累计 unique 物品 ≥ 阈值

纯逻辑、无 asyncio——供 AutonomousLoop（每 tick 更新）或 self_evolution 学习循环调用。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..benchmark.criteria import TECH_TREE_KEY_ITEMS


@dataclass
class TrainingTracker:
    """累计学习信号，判定是否「训练充分」可切 learn→live。

    Args:
        tech_tree_targets: 视为技术树关键节点的物品（默认复用 benchmark 的 key items）。
        recent_window: 「近期成功率」窗口大小（最近 N 个任务）。
        min_coverage: 判据①覆盖率阈值。
        min_recent_rate: 判据②近期成功率阈值。
        min_recent_samples: 判据②要求的最少样本数（避免几个样本就误触发）。
        min_items_discovered: 判据③物品发现数阈值。
    """

    tech_tree_targets: tuple[str, ...] = TECH_TREE_KEY_ITEMS
    recent_window: int = 20
    min_coverage: float = 0.8
    min_recent_rate: float = 0.7
    min_recent_samples: int = 20
    min_items_discovered: int = 15

    _discovered: set[str] = field(default_factory=set)
    _recent: deque[bool] = field(default_factory=deque)

    def __post_init__(self) -> None:
        # 把 deque 绑定到 recent_window 上限
        self._recent = deque(maxlen=self.recent_window)

    # ── 信号采集 ────────────────────────────────────────────────────────────

    def update_discovered(self, inventory: dict[str, int] | None) -> None:
        """从 inventory 快照累计已发现的 unique 物品（count > 0）。"""
        if not inventory:
            return
        for item, count in inventory.items():
            if isinstance(count, (int, float)) and count > 0:
                self._discovered.add(item)

    def record_task_result(self, success: bool) -> None:
        """记录单个任务的自我验证结果（True=通过）。"""
        self._recent.append(bool(success))

    # ── 指标 ──────────────────────────────────────────────────────────────────

    @property
    def items_discovered_count(self) -> int:
        return len(self._discovered)

    def tech_tree_coverage(self) -> float:
        """技术树覆盖率（基于已发现物品）。"""
        if not self.tech_tree_targets:
            return 0.0
        have = sum(1 for t in self.tech_tree_targets if t in self._discovered)
        return have / len(self.tech_tree_targets)

    def recent_success_rate(self) -> float:
        """最近窗口内的任务成功率（无样本 → 0.0）。"""
        if not self._recent:
            return 0.0
        return sum(1 for x in self._recent if x) / len(self._recent)

    # ── 判据 ──────────────────────────────────────────────────────────────────

    def sufficiency(self) -> tuple[bool, str | None]:
        """三选一判据。返回 (是否充分, 触发判据名)。

        ① 技术树覆盖 ≥ min_coverage
        ② 近期成功率 ≥ min_recent_rate 且样本数 ≥ min_recent_samples
        ③ 物品发现数 ≥ min_items_discovered
        """
        if self.tech_tree_coverage() >= self.min_coverage:
            return True, "tech_tree_coverage"
        if (
            len(self._recent) >= self.min_recent_samples
            and self.recent_success_rate() >= self.min_recent_rate
        ):
            return True, "recent_success_rate"
        if self.items_discovered_count >= self.min_items_discovered:
            return True, "items_discovered"
        return False, None

    def is_sufficient(self) -> bool:
        """是否训练充分（任一判据达标）。"""
        return self.sufficiency()[0]

    def summary(self) -> dict[str, Any]:
        """可观测快照（供 benchmark / 日志）。"""
        return {
            "items_discovered": self.items_discovered_count,
            "tech_tree_coverage": round(self.tech_tree_coverage(), 3),
            "recent_success_rate": round(self.recent_success_rate(), 3),
            "recent_samples": len(self._recent),
            "is_sufficient": self.is_sufficient(),
        }
