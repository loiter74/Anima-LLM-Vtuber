"""一次性：让 LLM 自主生成 craft iron_pickaxe 代码（自我演化精神），失败则 fallback
执行标准 craft code。确保 iron_pickaxe 真实造出（goal 达成）。

前置：bot 已有 iron_ingot + stick + crafting_table（重连同步），table 在 bot 旁。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from loguru import logger
from openai import AsyncOpenAI

for _line in Path(".env").read_text(encoding="utf-8").splitlines():
    _s = _line.strip()
    if "=" in _s and not _s.startswith("#"):
        _k, _v = _s.split("=", 1)
        os.environ.setdefault(_k, _v.strip().strip('"').strip("'"))

from animetta.tools.minecraft.core.bridge import MinecraftBridge  # noqa: E402
from animetta.tools.minecraft.core.config import (  # noqa: E402
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftMode,
    MinecraftViewerConfig,
)
from animetta.tools.minecraft.skill.code_generator import generate_with_iteration  # noqa: E402
from animetta.tools.minecraft.skill.verifier import verify  # noqa: E402

FALLBACK_CODE = "\n".join(
    [
        "await craft('iron_pickaxe', 1);",
        "const s = await status();",
        "return 'iron_pickaxe=' + (s.inventory['iron_pickaxe'] || 0);",
    ]
)


class DeepSeekLLM:
    def __init__(self):
        self._c = AsyncOpenAI(
            base_url="https://api.deepseek.com/v1", api_key=os.environ["DEEPSEEK_API_KEY"]
        )

    async def chat(self, messages):
        r = await self._c.chat.completions.create(
            model="deepseek-chat", messages=messages, temperature=0, max_tokens=512
        )
        return type("R", (), {"content": r.choices[0].message.content})()


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

    llm = DeepSeekLLM()

    async def run_code(code: str) -> dict:
        return await bridge.send_command(
            "eval_code", {"code": code, "timeout": 60_000}, timeout=70.0
        )

    logger.info("=== 尝试 1: LLM 自主生成 craft iron_pickaxe code ===")
    gen = await generate_with_iteration(
        "Craft 1 iron_pickaxe (you have iron_ingot + stick + crafting_table nearby). Just call craft('iron_pickaxe',1).",
        ["has_iron_pickaxe >= 1"],
        run_code,
        llm,
        max_iters=4,
    )
    if gen.success:
        logger.success(f"LLM 自主 codegen 成功 (round {gen.rounds})")
    else:
        logger.warning(f"LLM codegen 失败 ({gen.error[:120]}), fallback 标准craft code")
        r = await run_code(FALLBACK_CODE)
        logger.info(f"fallback craft: {r.get('status')} — {r.get('result')}")

    # verify
    st = await bridge.send_command("status")
    rd = st.get("result") if isinstance(st.get("result"), dict) else {}
    inv = rd.get("inventory", {}) if isinstance(rd, dict) else {}
    snapshot = {
        "inventory": inv,
        "position": rd.get("position"),
        "health": rd.get("health"),
        "food": rd.get("food"),
    }
    vr = await verify("craft iron_pickaxe", ["has_iron_pickaxe >= 1"], snapshot, llm=None)
    if vr.passed:
        logger.success(
            f"★★★ GOAL ACHIEVED: iron_pickaxe={inv.get('iron_pickaxe', 0)} (verify gate={vr.gate}) ★★★"
        )
    else:
        logger.error(f"iron_pickaxe NOT crafted. inv={inv}")
    logger.info(f"final inventory: {inv}")
    await asyncio.sleep(40)
    await bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())
