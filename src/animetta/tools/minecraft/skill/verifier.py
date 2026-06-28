"""Self-verification (mc-bot-voyager-learning T4).

论文 Self-Verification 的双重优化：
  闸1 · 确定性 inventory 检查（快、零成本、先跑）—— 大部分造工具/收集任务可秒判
  闸2 · LLM 判断（仅当闸1 判不了的模糊任务，如"建庇护所"）

避免论文纯 LLM 验证的 token 成本与延迟。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# 支持: has_X / has_X >= N / has_X > N / has_X == N
_INV_COND = re.compile(r"has_(\w+)\s*(>=|>|==|<=|<)?\s*(\d+)?")


@dataclass
class VerifyResult:
    """自我验证结果。"""

    passed: bool
    gate: str = ""  # "deterministic" | "llm" | "none"
    reason: str = ""
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "gate": self.gate,
            "reason": self.reason,
            "failures": list(self.failures),
        }


def _check_inventory_condition(cond: str, inventory: dict[str, int]) -> bool | None:
    """检查单条 inventory 条件。

    返回 True/False 表示判定结果；返回 None 表示该条件不是 inventory 型
    （如 "is_day"、"has_shelter"），确定性闸判不了，需交给 LLM。
    """
    cond = cond.strip()
    m = _INV_COND.fullmatch(cond)
    if not m:
        return None
    item, op, num = m.group(1), m.group(2), m.group(3)
    have = inventory.get(item, 0)
    if num:  # 带阈值 → 确定量化判定（has_X >= N）
        threshold = int(num)
        if op == ">=":
            return have >= threshold
        if op == ">":
            return have > threshold
        if op == "==":
            return have == threshold
        if op == "<=":
            return have <= threshold
        if op == "<":
            return have < threshold
        return have >= threshold
    # bare has_X：inventory 有则 True，无则 None
    # （has_shelter/has_house 这类模糊状态无法确定性判定，交 LLM 闸）
    return True if have >= 1 else None


def verify_deterministic(
    success_criteria: list[str], inventory: dict[str, int]
) -> VerifyResult | None:
    """闸1：纯确定性 inventory 检查。

    - 所有条件都是 inventory 型且全通过 → passed=True
    - 任一 inventory 条件失败（且无判不了的）→ passed=False
    - 含非 inventory 条件（判不了）→ 返回 None，需 LLM 闸
    - 空条件列表 → None（无可判定标准）
    """
    if not success_criteria:
        return None

    results: list[tuple[str, bool | None]] = []
    uncheckable = False
    for cond in success_criteria:
        r = _check_inventory_condition(cond, inventory)
        results.append((cond, r))
        if r is None:
            uncheckable = True

    if uncheckable:
        return None  # 交给 LLM

    failures = [c for c, r in results if r is False]
    return VerifyResult(
        passed=len(failures) == 0,
        gate="deterministic",
        failures=failures,
        reason="all inventory conditions satisfied" if not failures else f"failed: {failures}",
    )


async def verify_llm(
    task: str,
    success_criteria: list[str],
    status_snapshot: dict[str, Any],
    llm: Any,
) -> VerifyResult:
    """闸2：LLM 判断模糊任务（建造/探索等）。"""
    if llm is None:
        return VerifyResult(
            passed=False, gate="none", reason="no LLM available for fuzzy verification"
        )

    prompt = (
        f"You are a Minecraft task verifier. Decide if the task is accomplished.\n\n"
        f"Task: {task}\n"
        f"Success criteria: {success_criteria}\n"
        f"Current state:\n"
        f"  position: {status_snapshot.get('position')}\n"
        f"  health: {status_snapshot.get('health')}, food: {status_snapshot.get('food')}\n"
        f"  inventory: {status_snapshot.get('inventory')}\n\n"
        f"Answer ONLY 'YES' or 'NO' on the first line, then one short sentence of reason."
    )
    try:
        resp = await llm.chat(messages=[{"role": "user", "content": prompt}])
        content = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        return VerifyResult(passed=False, gate="llm", reason=f"LLM verify error: {e}")

    first = content.strip().split("\n", 1)[0].strip().upper()
    passed = first.startswith("YES")
    return VerifyResult(passed=passed, gate="llm", reason=content.strip()[:200])


async def verify(
    skill_or_task: Any,
    success_criteria: list[str],
    status_snapshot: dict[str, Any],
    llm: Any = None,
) -> VerifyResult:
    """双重验证入口：先确定性闸，判不了再 LLM 闸。

    Args:
        skill_or_task: Skill 对象或任务字符串（取 name/id 作 task 标签）
        success_criteria: 后置条件列表（如 ["has_iron_pickaxe >= 1"]）
        status_snapshot: bot 状态快照（含 inventory/position/health/food）
        llm: 可选 LLM service（闸2 用）
    """
    task = (
        getattr(skill_or_task, "name", None)
        or getattr(skill_or_task, "id", None)
        or str(skill_or_task)
    )
    inv = status_snapshot.get("inventory", {}) if isinstance(status_snapshot, dict) else {}

    det = verify_deterministic(success_criteria, inv)
    if det is not None:
        logger.info(f"[Verifier] deterministic gate: passed={det.passed} — {det.reason}")
        return det

    logger.info("[Verifier] deterministic gate inconclusive, falling back to LLM")
    return await verify_llm(task, success_criteria, status_snapshot, llm)
