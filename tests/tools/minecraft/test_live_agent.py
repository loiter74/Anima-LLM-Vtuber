"""T11/T12: LiveAgent 直播选技能 + 兜底回落 (mc-bot-voyager-learning)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.autonomous.live_agent import LiveAgent
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import Skill, SkillResult

# ── Helpers ──────────────────────────────────────────────────────────────────


def _skill(
    id_: str,
    name: str,
    *,
    success_count: int = 0,
    fail_count: int = 0,
    validated: bool = True,
) -> Skill:
    return Skill(
        id=id_,
        name=name,
        description=f"skill {name}",
        tags=["live"],
        validated=validated,
        success_count=success_count,
        fail_count=fail_count,
    )


# ── T11: select_skill ────────────────────────────────────────────────────────


async def test_select_skill_ranks_by_goal_relevance():
    """goal 相关度优先：collect wood 命中 skill A（而非 mine stone）。"""
    lib = SkillLibrary()
    await lib.save_skill(_skill("a", "collect wood", success_count=10))
    await lib.save_skill(_skill("b", "mine stone", success_count=100))  # 更高 success_rate 但不相关

    agent = LiveAgent(lib, AsyncMock())
    picked = await agent.select_skill("collect wood")

    assert picked is not None
    assert picked.id == "a"


async def test_select_skill_falls_back_to_success_rate_when_no_relevance():
    """无 goal 相关时按 success_rate 排序。"""
    lib = SkillLibrary()
    await lib.save_skill(_skill("low", "alpha", success_count=2, fail_count=8))  # 0.2
    await lib.save_skill(_skill("high", "beta", success_count=9, fail_count=1))  # 0.9

    agent = LiveAgent(lib, AsyncMock())
    picked = await agent.select_skill("completely unrelated goal")

    assert picked is not None
    assert picked.id == "high"


async def test_select_skill_excludes_unvalidated():
    """未 validated（verified）的技能不被直播期选中。"""
    lib = SkillLibrary()
    await lib.save_skill(_skill("unverified", "collect wood", validated=False))
    await lib.save_skill(_skill("ok", "collect wood", success_count=5))

    agent = LiveAgent(lib, AsyncMock())
    picked = await agent.select_skill("collect wood")

    assert picked is not None
    assert picked.id == "ok"


async def test_select_skill_returns_none_when_empty():
    agent = LiveAgent(SkillLibrary(), AsyncMock())
    assert await agent.select_skill("anything") is None


# ── T11/T12: run_goal ────────────────────────────────────────────────────────


async def test_run_goal_success_updates_stats():
    lib = SkillLibrary()
    await lib.save_skill(_skill("a", "collect wood", success_count=10))
    bridge = AsyncMock()
    agent = LiveAgent(lib, bridge, fallback_fn=AsyncMock(return_value={"completed": True}))

    # execute 成功
    lib.execute_skill_by_id = AsyncMock(return_value=SkillResult(success=True, skill_id="a"))

    out = await agent.run_goal("collect wood")

    assert out["outcome"] == "success"
    assert out["skill_id"] == "a"
    assert out["fallback"] is False
    assert (await lib.get_skill("a")).success_count == 11  # update_success


async def test_run_goal_skill_fail_degrades_and_falls_back():
    """技能失败 → 计 fail_count；达阈值 → 降权 + 兜底。"""
    lib = SkillLibrary()
    # fail_count 已 2 → 本次失败 update_failure 到 3 ≥ threshold(3) → 降权
    await lib.save_skill(_skill("flaky", "collect wood", success_count=1, fail_count=2))
    bridge = AsyncMock()
    fb = AsyncMock(return_value={"completed": False})
    agent = LiveAgent(lib, bridge, degrade_threshold=3, fallback_fn=fb)

    lib.execute_skill_by_id = AsyncMock(
        return_value=SkillResult(success=False, skill_id="flaky", reason="no trees")
    )

    out = await agent.run_goal("collect wood")

    assert out["outcome"] == "fallback"
    assert out["degraded"] is True
    assert out["skill_id"] == "flaky"
    assert fb.await_count == 1  # 兜底被调用
    assert (await lib.get_skill("flaky")).validated is False  # 已降权


async def test_run_goal_skill_fail_below_threshold_no_degrade():
    """失败但未达阈值 → 不降权（仍 validated），但仍兜底。"""
    lib = SkillLibrary()
    await lib.save_skill(_skill("ok", "collect wood", success_count=5, fail_count=0))
    agent = LiveAgent(lib, AsyncMock(), degrade_threshold=3, fallback_fn=AsyncMock(return_value={"completed": False}))
    lib.execute_skill_by_id = AsyncMock(return_value=SkillResult(success=False, skill_id="ok"))

    out = await agent.run_goal("collect wood")

    assert out["outcome"] == "fallback"
    assert out["degraded"] is False
    assert (await lib.get_skill("ok")).validated is True  # 未降权
    assert (await lib.get_skill("ok")).fail_count == 1


async def test_run_goal_no_skill_falls_back():
    """无适配 verified 技能 → 直接兜底 Survival Runner。"""
    lib = SkillLibrary()
    fb = AsyncMock(return_value={"completed": True})
    agent = LiveAgent(lib, AsyncMock(), fallback_fn=fb)

    out = await agent.run_goal("whatever")

    assert out["outcome"] == "fallback"
    assert out["reason"] == "no_validated_skill"
    assert fb.await_count == 1


async def test_default_fallback_runs_survival_runner_when_bridge_down():
    """未注入 fallback_fn 时，默认走 Survival Runner；bridge 断 → completed=False（不抛）。"""
    lib = SkillLibrary()
    bridge = AsyncMock()
    bridge.is_running = False  # SurvivalRunner._send_command 将返回 None → phase 失败
    agent = LiveAgent(lib, bridge)  # 无 fallback_fn → 默认 Survival Runner

    out = await agent._fallback("goal", reason="test")

    assert out["outcome"] in ("fallback", "fallback_failed")
    assert out["fallback"] is True
