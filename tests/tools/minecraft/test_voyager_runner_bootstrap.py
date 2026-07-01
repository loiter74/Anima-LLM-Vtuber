"""T8: survival runner bootstrap skill extraction hook (mc-bot-voyager-learning)."""

from __future__ import annotations

from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import Skill, SkillStep
from animetta.tools.minecraft.survival.models import PhaseResult, SurvivalPhase
from animetta.tools.minecraft.survival.runner import SurvivalIronRunner


class _FakeExtractor:
    """extractor 替身：总是返回预设 skill，记录调用次数。"""

    def __init__(self, skill: Skill | None):
        self._skill = skill
        self.calls = 0

    async def extract(self, trace, context=None):
        self.calls += 1
        return self._skill


def _seed_skill() -> Skill:
    return Skill(
        id="seed_wood",
        name="collect_wood",
        description="gather oak logs",
        tags=["collection"],
        validated=False,
        steps=[SkillStep(name="collect", params={"block_type": "oak_log", "count": 5})],
    )


async def test_phase_extraction_saves_bootstrap_seed():
    """成功 phase 的动作序列 → extractor → 存库（validated=True，标 bootstrap）。"""
    lib = SkillLibrary()
    ext = _FakeExtractor(_seed_skill())
    runner = SurvivalIronRunner(bridge=None, skill_library=lib, skill_extractor=ext)

    pr = PhaseResult(phase=SurvivalPhase.WOOD, success=True)
    pr.record_action("collect", {"block_type": "oak_log", "count": 5}, True, "ok")

    await runner._extract_phase_skill(SurvivalPhase.WOOD, pr)

    saved = await lib.get_skill("seed_wood")
    assert saved is not None
    assert saved.validated is True
    assert "bootstrap" in saved.tags
    assert "survival-seed" in saved.tags
    assert ext.calls == 1


async def test_no_extractor_is_no_op():
    """未注入 extractor/library → 钩子不启用、不抛。"""
    runner = SurvivalIronRunner(bridge=None)
    pr = PhaseResult(phase=SurvivalPhase.WOOD, success=True)
    pr.record_action("collect", {"block_type": "oak_log", "count": 5}, True)

    await runner._extract_phase_skill(SurvivalPhase.WOOD, pr)  # 不应抛异常


async def test_failed_phase_not_extracted():
    """失败的 phase 不抽取（无假种子）。"""
    lib = SkillLibrary()
    ext = _FakeExtractor(_seed_skill())
    runner = SurvivalIronRunner(bridge=None, skill_library=lib, skill_extractor=ext)

    pr = PhaseResult(phase=SurvivalPhase.WOOD, success=False)
    await runner._extract_phase_skill(SurvivalPhase.WOOD, pr)

    assert ext.calls == 0
    assert await lib.get_skill("seed_wood") is None


async def test_extractor_returning_none_skips_save():
    """extractor 返回 None（如重复检测）→ 不存库、不抛。"""
    lib = SkillLibrary()
    ext = _FakeExtractor(None)
    runner = SurvivalIronRunner(bridge=None, skill_library=lib, skill_extractor=ext)

    pr = PhaseResult(phase=SurvivalPhase.WOOD, success=True)
    pr.record_action("collect", {"block_type": "oak_log", "count": 5}, True, "ok")

    await runner._extract_phase_skill(SurvivalPhase.WOOD, pr)

    assert ext.calls == 1
    assert await lib.get_skill("seed_wood") is None
