"""T3 spike — 验证云 LLM 能否生成可执行的 mineflayer JS（mc-bot-voyager-learning go/no-go 关卡）。

验证目标：
  云 LLM 收「挖一块橡木」任务 → 生成 JS → eval_code 沙箱执行 → 检查 inventory 出现 oak_log。

前置条件（运行前必须确认）：
  1. MC 服务器运行在 localhost:25565，且已 op AnimettaBot
  2. bot/node_modules 已 `npm install`
  3. 云 LLM 可用（ServicePool 已初始化，或见 llm_chat() 手动接入说明）

运行：
  PYTHONPATH=src python -m animetta.tools.minecraft.other.spike_eval_code

结果判读：
  PASS → 代码生成路线可行，继续 T4+（迭代提示/验证/课程...）
  FAIL → 止步！回 brainstorming 重选「动作序列 plan」路线（design.md 落地顺序 T3）
"""
from __future__ import annotations

import asyncio
import re
import sys

from loguru import logger

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import (
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftMode,
)

SYSTEM_PROMPT = """You write mineflayer bot code. Output ONLY a JavaScript code body (no markdown fences, no prose).

Available async API (all return Promises, use await):
- await collect(block_type, count)
- await craft(recipe, count)
- await smelt(item, fuel, count)
- await goto(x, y, z)
- await place(block_type, x, y, z)
- await attack(target)
- await status()         // -> {position, health, food, inventory}
- await waitFor(seconds)

Rules: minimal code, await every API call, no function definitions needed."""


def strip_code_fences(text: str) -> str:
    """LLM 可能包 ```js ... ```，剥离。"""
    m = re.search(r"```(?:js|javascript)?\s*\n?(.*?)```", text, re.S)
    return m.group(1).strip() if m else text.strip()


async def llm_chat(messages: list[dict]) -> str:
    """调云 LLM。优先 ServicePool 已配的 LLM；否则需在此手动接入直连 client。

    生产实现走 ServicePool._llm.chat(messages=...) -> {content}。
    若 ServicePool 未就绪，按下方注释接 OpenAI/GLM/DeepSeek 直连。
    """
    try:
        from animetta.core.service_pool import ServicePool

        if getattr(ServicePool, "_ready", False) and getattr(ServicePool, "_llm", None):
            resp = await ServicePool._llm.chat(messages=messages)
            return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        logger.warning(f"ServicePool LLM unavailable: {e}")

    # --- 直连 fallback（按需启用）---
    # from openai import AsyncOpenAI
    # client = AsyncOpenAI()  # 读 OPENAI_API_KEY / OPENAI_BASE_URL
    # resp = await client.chat.completions.create(model="gpt-4o", messages=messages)
    # return resp.choices[0].message.content

    raise RuntimeError(
        "No LLM available. Initialize ServicePool first (run Animetta main), "
        "or edit llm_chat() to use a direct OpenAI/GLM/DeepSeek client."
    )


async def generate_and_run(bridge: MinecraftBridge, task: str, max_iters: int = 4) -> bool:
    """生成 JS → eval_code → 失败喂错误重写，≤max_iters 轮。返回是否达成目标。"""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    last_error = ""

    for i in range(1, max_iters + 1):
        user = task if i == 1 else f"{task}\n\nPrevious code failed:\n{last_error}\n\nFix and output code again."
        messages.append({"role": "user", "content": user})

        logger.info(f"[spike] iter {i}/{max_iters}: generating code...")
        raw = await llm_chat(messages)
        code = strip_code_fences(raw)
        logger.info(f"[spike] generated code:\n{code}")
        messages.append({"role": "assistant", "content": raw})

        result = await bridge.send_command("eval_code", {"code": code, "timeout": 30000})
        if result.get("status") == "success":
            logger.info(f"[spike] eval_code success: {result.get('result')}")
            status = await bridge.send_command("status")
            result_data = status.get("result") if isinstance(status.get("result"), dict) else {}
            inv = result_data.get("inventory", {}) if isinstance(result_data, dict) else {}
            if any("oak_log" in k for k in inv):
                logger.success("[spike] PASS: oak_log in inventory — code-gen route VIABLE ✓")
                return True
            last_error = "Code ran but no oak_log in inventory (silent failure)"
        else:
            last_error = str(result.get("result", "unknown error"))
            logger.warning(f"[spike] eval_code failed: {last_error}")

    logger.error("[spike] FAIL: exhausted iterations without success — route may not be viable")
    return False


async def main() -> int:
    config = MinecraftConfig(
        enabled=True,
        mode=MinecraftMode.FALLBACK,
        bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot"),
    )
    bridge = MinecraftBridge(config, autonomous=False)
    if not await bridge.start():
        logger.error("[spike] bridge start failed — is MC server on localhost:25565?")
        return 2

    try:
        ok = await generate_and_run(bridge, "Collect 1 oak_log using the collect API.")
        return 0 if ok else 1
    finally:
        await bridge.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
