"""Voyager 自我演化主循环（mc-bot-voyager-learning）。

循环 ≤ MAX_ROUNDS(40) 轮：
  curriculum 出题 → code_generator 生成 JS(≤4 轮迭代) → eval_code 执行 → verifier 验证
  → 通过则存 verified 技能库 → 检查终止条件
终止：inventory 出现 iron_pickaxe，或轮次超过 MAX_ROUNDS。

LLM: DeepSeek(deepseek-chat, OpenAI 兼容)。MC: localhost:25565。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI

# 加载 .env（utf-8，避免 Windows GBK 解码中文注释失败）
for _line in Path(".env").read_text(encoding="utf-8").splitlines():
    _s = _line.strip()
    if "=" in _s and not _s.startswith("#"):
        _k, _v = _s.split("=", 1)
        os.environ.setdefault(_k, _v.strip().strip('"').strip("'"))

from animetta.tools.minecraft.autonomous.curriculum import next_task  # noqa: E402
from animetta.tools.minecraft.core.bridge import MinecraftBridge  # noqa: E402
from animetta.tools.minecraft.core.config import (  # noqa: E402
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftMode,
    MinecraftViewerConfig,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary  # noqa: E402
from animetta.tools.minecraft.skill.code_generator import (  # noqa: E402
    generate_with_iteration,
    to_skill,
)
from animetta.tools.minecraft.skill.code_seeds import get_code_seeds  # noqa: E402
from animetta.tools.minecraft.skill.predefined import get_predefined_skills  # noqa: E402
from animetta.tools.minecraft.skill.verifier import verify  # noqa: E402

MAX_ROUNDS = 40
GOAL_ITEM = "iron_pickaxe"


class DeepSeekLLM:
    """DeepSeek (OpenAI 兼容) 包装成 code_generator/curriculum 期望的 .chat 接口。"""

    def __init__(self, model: str = "deepseek-chat"):
        self._client = AsyncOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ["DEEPSEEK_API_KEY"],
        )
        self._model = model

    async def chat(self, messages: list[dict]):
        r = await self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0, max_tokens=1024
        )
        return type("R", (), {"content": r.choices[0].message.content})()


async def get_state(bridge: MinecraftBridge) -> tuple[dict, dict]:
    st = await bridge.send_command("status")
    rd = st.get("result") if isinstance(st.get("result"), dict) else {}
    inv = rd.get("inventory", {}) if isinstance(rd, dict) else {}
    state = {
        "inventory": inv,
        "position": rd.get("position"),
        "health": rd.get("health"),
        "food": rd.get("food"),
    }
    return state, inv


async def main() -> int:
    logger.info(f"[evo] MAX_ROUNDS={MAX_ROUNDS}, goal=craft {GOAL_ITEM}, LLM=deepseek-chat")
    llm = DeepSeekLLM()

    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    bridge.set_viewer_callback(
        lambda et, u: logger.success(f"[VIEWER] {et}: {u}") if et == "viewer_joined" else logger.info(f"[VIEWER] {et}: {u}")
    )
    if not await bridge.start():
        logger.error("[evo] bridge start failed")
        return 2
    await asyncio.sleep(10)
    await bridge.spectate_viewer("LUN077")
    await asyncio.sleep(2)

    lib = SkillLibrary()
    for s in get_predefined_skills() + get_code_seeds():
        await lib.save_skill(s)

    completed: list[str] = []
    failed: list[str] = []
    last_inv: dict = {}

    for rnd in range(1, MAX_ROUNDS + 1):
        if not bridge.is_running:
            logger.error("[evo] bridge not running — aborting evolution loop")
            break
        state, inv = await get_state(bridge)
        last_inv = inv
        if inv.get(GOAL_ITEM, 0) >= 1:
            logger.success(f"★ ROUND {rnd}: {GOAL_ITEM} 已造出！自我演化目标达成 ★  inv={inv}")
            break

        logger.info(f"=== ROUND {rnd}/{MAX_ROUNDS} | inv items={len(inv)} | top: {dict(list(inv.items())[:6])} ===")

        learned = [s.name for s in await lib.get_all_skills() if s.validated]
        try:
            task = await next_task(llm, state, completed, failed, learned)
        except Exception as e:
            logger.error(f"[evo] curriculum failed: {e}")
            failed.append(f"<round {rnd}>")
            await asyncio.sleep(5)
            continue

        logger.info(f"[evo] task='{task.task}' criteria={task.success_criteria}")
        if not task.task:
            logger.warning("[evo] empty task, skip")
            continue
        # 跳过与已完成高度重叠的任务
        if any(task.task.lower() in c.lower() for c in completed):
            logger.info("[evo] task already completed, skip")
            completed.append(task.task)
            continue

        relevant = await lib.search_skills(task.task, limit=3)

        async def run_code(code: str) -> dict:
            return await bridge.send_command(
                "eval_code", {"code": code, "timeout": 180_000}, timeout=200.0
            )

        gen = await generate_with_iteration(
            task.task, task.success_criteria, run_code, llm,
            max_iters=4, relevant_skills=relevant,
        )
        if not gen.success:
            logger.warning(f"[evo] code-gen failed after {gen.rounds} rounds: {gen.error[:150]}")
            failed.append(task.task)
            continue

        state2, inv2 = await get_state(bridge)
        last_inv = inv2
        snapshot = {
            "inventory": inv2,
            "position": state2.get("position"),
            "health": state2.get("health"),
            "food": state2.get("food"),
        }
        vr = await verify(task.task, task.success_criteria, snapshot, llm=llm)
        if vr.passed:
            logger.success(f"[evo] ROUND {rnd} PASSED: '{task.task}' (gate={vr.gate})")
            skill = to_skill(task.task, gen, postconditions=task.success_criteria)
            skill.validated = True
            await lib.save_skill(skill)
            completed.append(task.task)
            if inv2.get(GOAL_ITEM, 0) >= 1:
                logger.success(f"★ {GOAL_ITEM} 造出，演化终止 ★ final inv={inv2}")
                break
        else:
            logger.warning(f"[evo] verify failed: {vr.reason} | inv={inv2}")
            failed.append(task.task)

    else:
        logger.warning(f"[evo] 达 {MAX_ROUNDS} 轮上限，未造出 {GOAL_ITEM}。final inv={last_inv}")

    logger.info(f"[evo] DONE | completed={len(completed)} failed={len(failed)} | final inv={last_inv}")
    await asyncio.sleep(30)
    await bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
