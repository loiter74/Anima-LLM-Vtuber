"""T15: 端到端 @slow 测试 — Voyager learn→live 全流程（mc-bot-voyager-learning）。

需要真实环境，默认 @pytest.mark.slow 跳过。运行：
    PYTHONPATH=src python -m pytest tests/tools/minecraft/test_e2e_voyager.py \\
        -o addopts="" -p no:cacheprovider -m slow

前置条件（任一缺失即 skip）：
  1. Minecraft 服务器运行在 localhost:25565，AnimettaBot 已 op
  2. bot/node_modules 已 npm install
  3. DEEPSEEK_API_KEY（或 ServicePool 已配 LLM）可用

回归部分（survival runner + skill library 不破）由 tests/tools/minecraft/ 全套覆盖，
本文件只放真服务器 e2e。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.slow


def _infra_available() -> bool:
    """探测 e2e 所需基础设施是否就绪（仅看密钥；node/服务器可达性交给 bridge.start）。"""
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


@pytest.mark.asyncio
@pytest.mark.skipif(not _infra_available(), reason="需 DEEPSEEK_API_KEY + 真实 MC 服务器（e2e）")
async def test_learn_loop_runs_and_produces_summary():
    """真服务器：run_learning_loop 跑 ≤2 轮，返回结构正确的摘要（不要求达成金装备）。"""
    from animetta.tools.minecraft.core.bridge import MinecraftBridge
    from animetta.tools.minecraft.core.config import (
        MinecraftBotConfig,
        MinecraftConfig,
        MinecraftMode,
        MinecraftViewerConfig,
    )
    from animetta.tools.minecraft.other.self_evolution import DeepSeekLLM, run_learning_loop
    from animetta.tools.minecraft.skill.catalog import SkillLibrary
    from animetta.tools.minecraft.skill.code_seeds import get_code_seeds
    from animetta.tools.minecraft.skill.predefined import get_predefined_skills

    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    if not await bridge.start():
        pytest.skip("MC 服务器未运行（localhost:25565）—— e2e 跳过")

    try:
        lib = SkillLibrary()
        for s in get_predefined_skills() + get_code_seeds():
            await lib.save_skill(s)
        llm = DeepSeekLLM()

        # 临时把 MAX_ROUNDS 压到 2，避免 e2e 跑满 60 轮（改模块全局；run_learning_loop 动态查找）。
        # 注：conftest 把 animetta.tools.minecraft stub 成轻量包，`import a.b.c as evo` 会抛
        # ImportError；该模块已由上方 `from ... import` 导入 sys.modules，直接取即可。
        import sys

        evo = sys.modules["animetta.tools.minecraft.other.self_evolution"]
        original = evo.MAX_ROUNDS
        evo.MAX_ROUNDS = 2
        try:
            summary = await run_learning_loop(bridge, lib, llm)
        finally:
            evo.MAX_ROUNDS = original

        assert isinstance(summary, dict)
        assert "completed" in summary and "discovered" in summary
        assert summary["give_mode"] is False  # mc-evo-purity：默认无 give
        assert summary["total_rounds"] <= 2
    finally:
        await bridge.stop()


@pytest.mark.asyncio
@pytest.mark.skipif(not _infra_available(), reason="需 DEEPSEEK_API_KEY + 真实 MC 服务器（e2e）")
async def test_live_agent_falls_back_to_survival_runner_on_empty_library():
    """真服务器：直播期空 verified 库 → LiveAgent 回落 Survival Runner（兜底链路通）。"""
    from animetta.tools.minecraft.autonomous.live_agent import LiveAgent
    from animetta.tools.minecraft.core.bridge import MinecraftBridge
    from animetta.tools.minecraft.core.config import (
        MinecraftBotConfig,
        MinecraftConfig,
        MinecraftMode,
    )
    from animetta.tools.minecraft.skill.catalog import SkillLibrary

    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.LIVE,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    if not await bridge.start():
        pytest.skip("MC 服务器未运行（localhost:25565）—— e2e 跳过")

    try:
        lib = SkillLibrary()  # 空 verified 库
        agent = LiveAgent(lib, bridge)
        result = await agent.run_goal("collect wood")

        # 空库 → 必然兜底 Survival Runner（outcome ∈ fallback / fallback_failed）
        assert result.get("fallback") is True
        assert result.get("reason") == "no_validated_skill"
    finally:
        await bridge.stop()
