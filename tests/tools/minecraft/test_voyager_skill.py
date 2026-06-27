"""Tests for Voyager code-body skill + self-verification (mc-bot-voyager-learning)."""

from __future__ import annotations

import asyncio

from animetta.tools.minecraft.skill.code_seeds import get_code_seeds
from animetta.tools.minecraft.skill.verifier import (
    verify,
    verify_deterministic,
)


def test_code_seed_structure():
    """code-body 技能结构正确：body.type=code、validated=True、有可验证 postconditions。"""
    seeds = get_code_seeds()
    assert len(seeds) >= 1
    skill = seeds[0]
    assert skill.body.get("type") == "code"
    assert skill.body.get("code", "").strip()
    assert skill.body.get("api_version") == "v1"
    assert skill.validated is True
    assert skill.postconditions


def test_code_seed_uses_only_restricted_api():
    """code 只用受限 API（collect/craft/status），不碰 bot/require/process。"""
    code = get_code_seeds()[0].body["code"]
    for forbidden in ["bot.", "require(", "process.", "globalThis", "eval("]:
        assert forbidden not in code, f"code touches forbidden token: {forbidden}"
    assert "await collect" in code
    assert "await craft" in code


def test_verifier_deterministic_pass():
    """确定性闸：inventory 满足 postcondition → passed。"""
    skill = get_code_seeds()[0]
    result = verify_deterministic(skill.postconditions, {"wooden_pickaxe": 1})
    assert result is not None
    assert result.passed is True
    assert result.gate == "deterministic"


def test_verifier_deterministic_fail():
    """确定性闸：inventory 不满足 → failed + failures 列表含缺失项。"""
    skill = get_code_seeds()[0]
    result = verify_deterministic(skill.postconditions, {"oak_planks": 2})
    assert result is not None
    assert result.passed is False
    assert any("wooden_pickaxe" in f for f in result.failures)


def test_verifier_deterministic_inconclusive_for_fuzzy():
    """模糊条件（非 inventory 型如 has_shelter）→ None，交 LLM 闸。"""
    assert verify_deterministic(["has_shelter"], {"cobblestone": 10}) is None
    assert verify_deterministic([], {"oak_log": 1}) is None


def test_verify_async_deterministic_path():
    """verify() 异步入口：确定性可判时走闸1，无 LLM 也能判定。"""
    skill = get_code_seeds()[0]
    snapshot = {"inventory": {"wooden_pickaxe": 1}, "health": 20}
    result = asyncio.run(verify(skill, skill.postconditions, snapshot, llm=None))
    assert result.passed is True
    assert result.gate == "deterministic"


def test_verify_async_fuzzy_without_llm():
    """模糊任务 + 无 LLM → 不通过（gate=none）。"""
    snapshot = {"inventory": {}, "health": 20}
    result = asyncio.run(verify("build shelter", ["has_shelter"], snapshot, llm=None))
    assert result.passed is False
    assert result.gate in ("none", "llm")


def test_seed_loads_into_library():
    """code-body seed 能存入 SkillLibrary 并被检索（验证与库的集成）。"""
    from animetta.tools.minecraft.skill.catalog import SkillLibrary

    async def run():
        lib = SkillLibrary()
        for seed in get_code_seeds():
            await lib.save_skill(seed)
        all_skills = await lib.get_all_skills()
        assert any(s.body.get("type") == "code" for s in all_skills)
        # match_skills 按 precondition + success_rate 排序，seed(validated, success_count=1) 应可匹配
        matched = await lib.match_skills({"health": 20})
        assert any(s.id == "voyager_craft_wooden_pickaxe" for s in matched)

    asyncio.run(run())


def test_code_generator_iteration_success_on_retry():
    """论文迭代提示：第1轮失败→喂错误→第2轮成功（mock LLM + mock 执行）。"""
    from animetta.tools.minecraft.skill.code_generator import (
        generate_with_iteration,
        to_skill,
    )

    class _Resp:
        def __init__(self, content):
            self.content = content

    class MockLLM:
        def __init__(self, responses):
            self._r = responses
            self._i = 0

        async def chat(self, messages):
            c = self._r[self._i]
            self._i += 1
            return _Resp(c)

    async def mock_run(code: str):
        # 第一段代码（含 'bad'）失败，第二段成功
        if "bad" in code:
            return {"status": "error", "result": "TypeError: bad is not defined"}
        return {"status": "success", "result": "ok"}

    llm = MockLLM(["await collect('oak_log', 1)  // bad", "await collect('oak_log', 1)"])

    async def run():
        return await generate_with_iteration(
            "collect 1 oak log",
            ["has_oak_log >= 1"],
            mock_run,
            llm,
            max_iters=4,
        )

    result = asyncio.run(run())
    assert result.success is True
    assert result.rounds == 2  # 第 2 轮成功（验证失败反馈触发了重写）
    assert "bad" not in result.code

    skill = to_skill("collect 1 oak log", result, postconditions=["has_oak_log >= 1"])
    assert skill.body.get("type") == "code"
    assert skill.validated is False  # 待 verifier 验证


def test_code_generator_exhaustion_returns_failure():
    """迭代提示：连续失败到 max_iters 上限 → success=False。"""
    from animetta.tools.minecraft.skill.code_generator import generate_with_iteration

    class _Resp:
        def __init__(self, c):
            self.content = c

    class MockLLM:
        async def chat(self, messages):
            return _Resp("await collect('oak_log', 1)  // always bad")

    async def always_fail(code: str):
        return {"status": "error", "result": "always fails"}

    async def run():
        return await generate_with_iteration(
            "collect oak", ["has_oak_log >= 1"], always_fail, MockLLM(), max_iters=3
        )

    result = asyncio.run(run())
    assert result.success is False
    assert result.rounds == 3  # 跑满上限
