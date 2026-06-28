"""一次性：让 bot 穿戴全套金装备（eval_code 执行 equip 4 件），验证 ArmorItems。

bot 已 craft 全套 golden_*（在 inventory）。此脚本让 bot.equip 穿戴。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import (
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftMode,
    MinecraftViewerConfig,
)

EQUIP_CODE = "\n".join(
    [
        "await equip('golden_helmet', 'head');",
        "await equip('golden_chestplate', 'chest');",
        "await equip('golden_leggings', 'legs');",
        "await equip('golden_boots', 'feet');",
        "return 'equipped full gold armor';",
    ]
)


async def main():
    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    bridge.set_viewer_callback(lambda et, u: logger.info(f"[VIEWER] {et}: {u}"))
    await bridge.start()
    await asyncio.sleep(10)
    await bridge.spectate_viewer("LUN077")
    await asyncio.sleep(2)
    logger.info("equipping full gold armor via eval_code...")
    r = await bridge.send_command(
        "eval_code", {"code": EQUIP_CODE, "timeout": 60_000}, timeout=70.0
    )
    logger.info(f"eval_code: {r.get('status')} — {r.get('result')}")
    await asyncio.sleep(45)  # 保持 bot 在线，供外部 RCON 查 ArmorItems
    await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
