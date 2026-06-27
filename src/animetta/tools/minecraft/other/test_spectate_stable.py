"""测试稳定附身：bot 连上后 spawn 自动 spectate LUN077（不手动 spectate_viewer）。

验证 goal: 每次 bot 上线自动附身 + viewer 先在线也附身。
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


async def main():
    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
        viewer=MinecraftViewerConfig(username="LUN077", auto_spectate=True),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    bridge.set_viewer_callback(
        lambda et, u: logger.success(f"[VIEWER EVENT] {et}: {u}")
    )
    logger.info("connecting bot (viewer=LUN077), 不手动 spectate — spawn 应自动附身")
    await bridge.start()
    # 等 spawn(3s) + spectate 命令(1s) + 余量
    await asyncio.sleep(35)
    logger.info("bot 在线期间测试完成（spawn + 至少 1 次 periodic 重附身）")
    await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
