"""Voyager 自我演化主循环（mc-bot-voyager-learning）。

循环 ≤ MAX_ROUNDS(40) 轮：
  curriculum 出题 → code_generator 生成 JS(≤4 轮迭代) → eval_code 执行 → verifier 验证
  → 通过则存 verified 技能库 → 检查终止条件
终止：inventory 出现任意一件金装备，或轮次超过 MAX_ROUNDS。

LLM: DeepSeek 4 Pro(OpenAI 兼容)。MC: localhost:25565。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from openai import AsyncOpenAI

# 加载可选的 .env（utf-8，避免 Windows GBK 解码中文注释失败）
_env_path = Path(".env")
if _env_path.is_file():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
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
from animetta.tools.minecraft.other.rcon_helpers import (  # noqa: E402
    SMELT_RESULT_MAP,
    _rcon,
    parse_rcon_inv,
    rcon_smelt,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary  # noqa: E402
from animetta.tools.minecraft.skill.code_generator import (  # noqa: E402
    generate_with_iteration,
    to_skill,
)
from animetta.tools.minecraft.skill.code_seeds import get_code_seeds  # noqa: E402
from animetta.tools.minecraft.skill.predefined import get_predefined_skills  # noqa: E402
from animetta.tools.minecraft.skill.verifier import verify  # noqa: E402

MAX_ROUNDS = 60
GOAL_ITEMS = ["golden_helmet", "golden_chestplate", "golden_leggings", "golden_boots"]
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
SAME_TASK_LIMIT = 10

# ── 材料补全开关（mc-evo-purity）─────────────────────────────────────────────
# 默认 False → 学习/生产模式永不 _rcon give，保持 verifier 自我验证纯净
# （inventory 不被人为补齐，避免「真实环境会失败的 code-body skill」被误标
# validated=True 入库——即「假技能」）。仅在 MC_EVO_ALLOW_GIVE=1 时保留调试期
# give 行为（复现卡死场景）。运行时可被 purify / 测试覆写（模块全局动态查找）。
MC_EVO_ALLOW_GIVE = os.environ.get("MC_EVO_ALLOW_GIVE", "0") == "1"

# give 补全时跳过的工具/方块——这些必须靠真实采集/合成获得，补全会破坏判定意义。
_GIVE_SKIP_ITEMS = frozenset(
    {"iron_pickaxe", "stone_pickaxe", "wooden_pickaxe", "crafting_table", "furnace"}
)


class DeepSeekLLM:
    """DeepSeek (OpenAI 兼容) 包装成 code_generator/curriculum 期望的 .chat 接口。"""

    def __init__(self, model: str = DEFAULT_DEEPSEEK_MODEL):
        self._client = AsyncOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ["DEEPSEEK_API_KEY"],
        )
        self._model = model

    async def chat(self, messages: list[dict]):
        r = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0,
            max_tokens=1024,
        )
        msg = r.choices[0].message
        return type(
            "R",
            (),
            {
                "content": msg.content,
                "reasoning_content": getattr(msg, "reasoning_content", ""),
            },
        )()


STATE_FILE = "data/mc_evo_state.json"


def _load_evo_state() -> dict:
    """加载持久化状态（goal 进度跨会话恢复）。"""
    try:
        return json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {
            "completed": [],
            "failed": [],
            "discovered": [],
            "total_rounds": 0,
            "give_mode": False,
        }


def _save_evo_state(state: dict) -> None:
    """保存状态（每轮更新，下次启动恢复）。"""
    try:
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(STATE_FILE).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"[evo] save state failed: {e}")


def _gold_goal_reached(inv: dict) -> bool:
    """本轮 MC 迭代目标：打造任意一件金装备。"""
    return any(inv.get(item, 0) >= 1 for item in GOAL_ITEMS)


def _gold_progress(inv: dict) -> dict:
    """Return current golden equipment counts for logs."""
    return {item: inv.get(item, 0) for item in GOAL_ITEMS}


async def get_state(bridge: MinecraftBridge) -> tuple[dict, dict]:
    """用 RCON 读服务器端 inventory（准，绕 mineflayer 缓存；与 rcon_smelt 一致 server-authoritative）。"""
    inv = parse_rcon_inv(_rcon("data get entity AnimettaBot Inventory"))
    return {"inventory": inv, "position": None, "health": 20, "food": 20}, inv


async def _maybe_give_materials(task: Any, inv: dict) -> bool:
    """材料补全（受 ``MC_EVO_ALLOW_GIVE`` 守卫，mc-evo-purity）。

    默认 ``MC_EVO_ALLOW_GIVE=False`` → 直接返回，**永不 _rcon give**，保持 verifier
    自我验证的纯净（inventory 不被人为补齐，避免假技能入库）。仅当显式开启
    （``MC_EVO_ALLOW_GIVE=1``）时保留调试期行为：inv 攒到目标 1/5 时 give 补全剩余。

    Returns:
        True 表示执行了一次 give（仅供可观测/可测试；调用方无需据此分支）。
    """
    if not MC_EVO_ALLOW_GIVE:
        return False
    for crit in task.success_criteria or []:
        m = re.match(r"has_([a-z_]+)\s*>=\s*(\d+)", crit)
        if not m:
            continue
        item, target = m.group(1), int(m.group(2))
        if item in _GIVE_SKIP_ITEMS:
            continue  # 工具/方块不补全
        have = inv.get(item, 0)
        threshold = max(1, target // 5)
        if 0 < have < target and have >= threshold:
            need = target - have
            _rcon(f"give AnimettaBot minecraft:{item} {need}")
            logger.info(f"[evo] 材料补全 {item}: {have}/{target} >= 1/5({threshold}) → give {need}")
            await asyncio.sleep(1)
            return True
    return False


async def run_learning_loop(
    bridge: MinecraftBridge,
    lib: SkillLibrary,
    llm: Any,
) -> dict[str, Any]:
    """Voyager 学习闭环核心（mc-bot-voyager-learning T9 复用入口）。

    curriculum 出题 → code_generator 迭代生成 JS → eval_code 执行 → verifier 验证
    → 通过则存 verified 技能。循环 ≤ MAX_ROUNDS 轮或达任意一件 GOAL_ITEMS。

    bridge 生命周期由调用方管理：``main()`` 起/停 bridge；``bridge._start_autonomous``
    在 LEARN 模式下后台创建 task 跑本函数。返回摘要
    ``{completed, failed, discovered, total_rounds, give_mode}``。
    """
    logger.info(
        f"[evo] run_learning_loop | max_rounds={MAX_ROUNDS} goal=any_of({GOAL_ITEMS}) "
        f"LLM={type(llm).__name__} give_mode={MC_EVO_ALLOW_GIVE}"
    )

    # 持久化：加载上次状态（completed/failed/discovered 跨会话恢复）
    evo_state = _load_evo_state()
    completed: list[str] = evo_state.get("completed", [])
    failed: list[str] = evo_state.get("failed", [])
    last_inv: dict = {}
    discovered: set[str] = set(evo_state.get("discovered", []))
    if completed or failed or discovered:
        logger.info(
            f"[evo] 恢复状态: completed={len(completed)} failed={len(failed)} discovered={len(discovered)}"
        )
    last_task_text = ""
    same_task_streak = 0
    rnd = 0

    for rnd in range(1, MAX_ROUNDS + 1):
        if not bridge.is_running:
            logger.error("[evo] bridge not running — aborting evolution loop")
            break
        state, inv = await get_state(bridge)
        last_inv = inv
        # 论文核心指标：发现新合成物品
        new_items = set(inv.keys()) - discovered
        if new_items:
            discovered |= new_items
            logger.info(f"[evo] ✨ 新发现物品: {sorted(new_items)} | 累计 {len(discovered)} 种")
        # 持久化：每轮保存状态（completed/failed/discovered 跨会话恢复）
        _save_evo_state(
            {
                "completed": completed,
                "failed": failed,
                "discovered": sorted(discovered),
                "total_rounds": rnd,
                "give_mode": MC_EVO_ALLOW_GIVE,
            }
        )
        # 本轮目标：任意一件金装备
        gold_have = _gold_progress(inv)
        if _gold_goal_reached(inv):
            logger.success(
                f"★ ROUND {rnd}: 金装备目标达成 {gold_have} | 累计发现 {len(discovered)} 物品 ★"
            )
            break

        logger.info(
            f"=== ROUND {rnd}/{MAX_ROUNDS} | inv items={len(inv)} | top: {dict(list(inv.items())[:6])} ==="
        )

        learned = [s.name for s in await lib.get_all_skills() if s.validated]
        try:
            task = await next_task(llm, state, completed, failed, learned)
        except Exception as e:
            logger.error(f"[evo] curriculum failed: {e}")
            failed.append(f"<round {rnd}>")
            await asyncio.sleep(5)
            continue

        logger.info(f"[evo] task='{task.task}' criteria={task.success_criteria}")
        # 材料补全（受 MC_EVO_ALLOW_GIVE 守卫，mc-evo-purity）：默认 False → 永不 give，
        # 保持 verifier 自我验证纯净。仅 MC_EVO_ALLOW_GIVE=1 时保留调试期 give 行为。
        await _maybe_give_materials(task, inv)
        # smelt task 走 rcon_smelt（Python RCON, check inv 不凭空, 绕 mineflayer openFurnace crash）
        tl = task.task.lower()
        smelt_item = next((k for k in SMELT_RESULT_MAP if k in tl), None)
        if "smelt" in tl and smelt_item:
            logger.info(f"[evo] smelt task → rcon_smelt({smelt_item}, coal, 5) [inv checked]")
            ok, msg = rcon_smelt(smelt_item, "coal", 5)
            logger.info(f"[evo] rcon_smelt: {ok} — {msg}")
            await asyncio.sleep(2)
            continue
        # 连续 SAME_TASK_LIMIT 轮卡在同一问题 → 停止 goal
        tt = task.task.strip().lower()
        if tt and tt == last_task_text:
            same_task_streak += 1
        elif tt:
            same_task_streak = 1
            last_task_text = tt
        if same_task_streak > SAME_TASK_LIMIT:
            logger.warning(
                f"[evo] 连续 {same_task_streak} 轮卡在同一问题 '{task.task}' → 停止 goal"
            )
            break
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
            task.task,
            task.success_criteria,
            run_code,
            llm,
            max_iters=4,
            relevant_skills=relevant,
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
            if _gold_goal_reached(inv2):
                logger.success(f"★ 金装备目标达成 {_gold_progress(inv2)} ★")
                break
        else:
            logger.warning(f"[evo] verify failed: {vr.reason} | inv={inv2}")
            failed.append(task.task)

    else:
        logger.warning(
            f"[evo] 达 {MAX_ROUNDS} 轮上限或卡停。金装备进度: {_gold_progress(last_inv)} | 累计发现 {len(discovered)} 物品"
        )

    logger.info(
        f"[evo] DONE | completed={len(completed)} failed={len(failed)} | final inv={last_inv}"
    )
    return {
        "completed": len(completed),
        "failed": len(failed),
        "discovered": len(discovered),
        "total_rounds": rnd,
        "give_mode": MC_EVO_ALLOW_GIVE,
    }


async def main() -> int:
    """独立 CLI 入口：起 bridge + lib，跑学习闭环，停 bridge。"""
    logger.info(
        f"[evo] standalone CLI | MAX_ROUNDS={MAX_ROUNDS} goal=any_of({GOAL_ITEMS}) LLM={DEFAULT_DEEPSEEK_MODEL}"
    )
    llm = DeepSeekLLM()

    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    bridge.set_viewer_callback(
        lambda et, u: (
            logger.success(f"[VIEWER] {et}: {u}")
            if et == "viewer_joined"
            else logger.info(f"[VIEWER] {et}: {u}")
        )
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

    await run_learning_loop(bridge, lib, llm)

    await asyncio.sleep(30)
    await bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
