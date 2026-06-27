"""端到端运行 Voyager skill（mc-bot-voyager-learning）。

流程：bot(AnimettaBot) 连 MC 服务器 → 执行 voyager_craft_wooden_pickaxe skill
（通过 eval_code 沙箱跑 code-body）→ 验证 inventory 出现 wooden_pickaxe。
viewer=LUN077：LUN077 用 MC 客户端连入服务器时，bot 自动 /gamemode spectator + /spectate 附身。

前置：MC 服务器已起在 localhost:25565，AnimettaBot+LUN077 已 op。
运行：PYTHONPATH=src python -m animetta.tools.minecraft.other.run_voyager_skill
"""
from __future__ import annotations

import asyncio
import sys

from loguru import logger

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import (
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftMode,
    MinecraftViewerConfig,
)
from animetta.tools.minecraft.skill.code_seeds import get_code_seeds
from animetta.tools.minecraft.skill.verifier import verify

GOAL_ITEM = "wooden_pickaxe"


async def main() -> int:
    skill = get_code_seeds()[0]  # voyager_craft_wooden_pickaxe
    logger.info(f"[run] skill={skill.id} postconditions={skill.postconditions}")

    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)

    def _on_viewer(event_type: str, username: str) -> None:
        if event_type == "viewer_joined":
            logger.success(f"[VIEWER] {username} 上线 → bot 自动附身 (spectate)")
        else:
            logger.info(f"[VIEWER] {event_type}: {username}")

    bridge.set_viewer_callback(_on_viewer)

    if not await bridge.start():
        logger.error("[run] bridge start failed — MC server on localhost:25565?")
        return 2

    # 等 bot 登录 + spawn + 世界加载
    await asyncio.sleep(10)

    # 主动附身 LUN077（LUN077 可能已先于 bot 在线，playerJoined 不触发，需手动 spectate）
    logger.info("[run] 附身 LUN077 → spectate...")
    sp = await bridge.spectate_viewer("LUN077")
    logger.info(f"[run] spectate: {sp.get('status')} — {sp.get('result')}")
    await asyncio.sleep(2)

    # 执行 skill：eval_code 跑 code-body
    logger.info(f"[run] 执行 skill code-body (eval_code, 最多 200s)...")
    code = skill.body["code"]
    result = await bridge.send_command(
        "eval_code", {"code": code, "timeout": 180_000}, timeout=200.0
    )
    logger.info(f"[run] eval_code status={result.get('status')} result={result.get('result')}")

    # 取 status 快照
    status_resp = await bridge.send_command("status")
    status_data = status_resp.get("result") if isinstance(status_resp.get("result"), dict) else {}
    inv = status_data.get("inventory", {}) if isinstance(status_data, dict) else {}
    snapshot = {
        "inventory": inv,
        "position": status_data.get("position"),
        "health": status_data.get("health"),
        "food": status_data.get("food"),
    }
    logger.info(f"[run] final inventory: {inv}")

    # 自我验证（确定性闸）
    vr = await verify(skill, skill.postconditions, snapshot, llm=None)
    if vr.passed:
        logger.success(f"[run] ★ GOAL MET ★ wooden_pickaxe={inv.get(GOAL_ITEM, 0)} | verify gate={vr.gate}")
        goal_met = True
    else:
        logger.error(f"[run] goal NOT met: {vr.reason} | inv={inv}")
        goal_met = False

    # 保持 bot 在线，让 LUN077 可随时登录附身
    logger.info("[run] bot 保持在线，等待 LUN077 登录附身（MC 客户端连 localhost:25565）。保持 10 分钟...")
    try:
        await asyncio.sleep(600)
    except KeyboardInterrupt:
        pass
    await bridge.stop()
    return 0 if goal_met else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
