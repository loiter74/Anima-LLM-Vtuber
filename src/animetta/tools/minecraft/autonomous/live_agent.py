"""直播期 agent（mc-bot-voyager-learning T11/T12）。

直播期**只复用**独立复验后的 ``trusted`` 技能，不生成新代码——这是直播可靠性的根。
选技能：precondition 匹配 + goal 相关度 + success_rate 排序；失败计 fail_count，连续
K 次连续失败后降为 candidate，不再被直播期信任。全部可用技能失败 / 无适配技能 /
agent 卡死时，自动回落 Survival Runner 跑确定性流程（T12 兜底）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from ..core.bridge import MinecraftBridge
    from ..skill.catalog import SkillLibrary
    from ..skill.models import Skill


class LiveAgent:
    """直播期技能选择 + 执行 + 兜底。"""

    def __init__(
        self,
        library: SkillLibrary,
        bridge: MinecraftBridge,
        *,
        degrade_threshold: int = 3,
        fallback_fn: Any = None,
        session_id: str = "live-agent",
    ):
        self._library = library
        self._bridge = bridge
        # 连续失败 K 次降权：skill.fail_count ≥ 此值 → validated=False（直播期不再信任）
        self._degrade_threshold = degrade_threshold
        # 可注入的兜底回调（默认走 Survival Runner）；测试可注入 mock
        self._fallback_fn = fallback_fn
        self._session_id = session_id

    # ── T11: 选技能 ────────────────────────────────────────────────────────

    async def select_skill(self, goal: str, context: dict[str, Any] | None = None) -> Skill | None:
        """从 verified(validated) 库按 precondition 匹配 + goal 相关度 + success_rate 选最佳技能。

        Returns:
            最佳适配 Skill，或 None（无 validated 技能 / 无 precondition 满足者）。
        """
        context = context or {}
        trusted = await self._library.match_trusted_skills(context, limit=10)
        if not trusted:
            return None

        # goal 相关度细化：关键词重叠优先，其次 success_rate，最后 fail_count 升序
        goal_words = {w for w in goal.lower().split() if len(w) > 1}

        def relevance(s: Skill) -> int:
            text = f"{s.name} {s.description}".lower()
            return sum(1 for w in goal_words if w in text)

        trusted.sort(key=lambda s: (-relevance(s), -s.success_rate, s.consecutive_failures))
        return trusted[0]

    # ── T11/T12: 执行 + 失败计数 + 兜底 ────────────────────────────────────

    async def run_goal(self, goal: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """直播期处理一个 goal：选 verified 技能执行；失败/无技能 → Survival Runner 兜底。

        Returns:
            结果 dict（outcome ∈ success / fallback / fallback_failed）。
        """
        skill = await self.select_skill(goal, context)
        if skill is None:
            logger.info(f"[LiveAgent] 无适配 trusted 技能 → 兜底 Survival Runner: '{goal}'")
            return await self._fallback(goal, reason="no_trusted_skill")

        result = await self._library.execute_skill_by_id(skill.id, self._bridge)
        if result.success:
            await self._library.update_success(skill.id)
            logger.success(f"[LiveAgent] skill '{skill.name}' 成功完成 goal '{goal}'")
            return {"outcome": "success", "skill_id": skill.id, "fallback": False}

        # 失败 → 计 fail_count；K 次降权
        await self._library.update_failure(skill.id)
        degraded = False
        if skill.consecutive_failures >= self._degrade_threshold:
            await self._library.demote_skill(
                skill.id,
                reason=f"{skill.consecutive_failures} consecutive live failures",
                session_id=self._session_id,
            )
            degraded = True
            logger.warning(
                f"[LiveAgent] skill '{skill.name}' 连续失败 {skill.consecutive_failures} 次 → candidate"
            )
        else:
            logger.warning(f"[LiveAgent] skill '{skill.name}' 失败 (fail_count={skill.fail_count})")

        # T12 兜底：技能失败 → 回落 Survival Runner 跑确定性流程
        fb = await self._fallback(goal, reason=f"skill_failed:{skill.name}")
        fb["degraded"] = degraded
        fb["skill_id"] = skill.id
        return fb

    async def _fallback(self, goal: str, reason: str = "") -> dict[str, Any]:
        """T12: 兜底回落 Survival Runner。可注入 fallback_fn（测试用），默认真实 runner。"""
        if self._fallback_fn is not None:
            fb = await self._fallback_fn(goal)
            if isinstance(fb, dict):
                fb.setdefault("outcome", "fallback")
                fb.setdefault("fallback", True)
                fb.setdefault("reason", reason)
                return fb
            return {"outcome": "fallback", "fallback": True, "reason": reason, "result": fb}

        # 默认：Survival Runner 确定性流程
        try:
            from ..survival.runner import SurvivalIronRunner

            runner = SurvivalIronRunner(self._bridge, skill_library=self._library)
            report = await runner.run()
            logger.info(f"[LiveAgent] 兜底 Survival Runner 完成: completed={report.completed}")
            return {
                "outcome": "fallback",
                "fallback": True,
                "reason": reason,
                "completed": report.completed,
            }
        except Exception as e:
            logger.error(f"[LiveAgent] 兜底 Survival Runner 异常: {e}")
            return {
                "outcome": "fallback_failed",
                "fallback": True,
                "reason": f"{reason}: {e}",
            }
