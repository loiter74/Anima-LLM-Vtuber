"""Code generator (mc-bot-voyager-learning T5) — 论文迭代提示核心。

LLM 生成 mineflayer JS 代码 → eval_code 沙箱执行 → 失败把「错误 + 状态 + 上版代码」
喂回 LLM 重写，≤max_iters 轮。成功则产出 code-body Skill 候选（待 verifier 验证后存库）。

这是 Voyager 论文的灵魂组件：通过环境反馈迭代修正 LLM 生成的代码。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .models import Skill

SYSTEM_PROMPT = """You write mineflayer bot code. Output ONLY a JavaScript code body (no markdown fences, no prose).

Available async API (all return Promises, use await):
- await collect(block_type, count)   // find+navigate+mine+pickup a BLOCK
- await craft(recipe, count)         // craft an ITEM (3x3 recipes need crafting_table nearby)
- await smelt(item, fuel, count)     // smelt in furnace: smelt('raw_iron','coal',3) -> iron_ingot
- await goto(x, y, z)
- await place(block_type, x, y, z)
- await attack(target)
- await status()         // -> {position:{x,y,z}, health, food, inventory:{<item>:<count>}}
- await waitFor(seconds)

CRITICAL RULES:
- status().inventory is a PLAIN OBJECT {item_name: count}, NOT an array.
  Read with `s.inventory['oak_log']` or `'oak_log' in s.inventory`.
  NEVER call .some/.map/.filter/.find on inventory — it has no array methods.
- collect() takes a BLOCK name: 'oak_log','stone','coal_ore','iron_ore','dirt'.
  Mining 'stone' drops 'cobblestone' (item). Mining 'iron_ore' drops 'raw_iron' (item).
  So to get cobblestone: collect('stone', N). For iron: collect('iron_ore', N) then smelt('raw_iron','coal',N).
- craft() takes an ITEM recipe: 'oak_planks','stick','crafting_table','wooden_pickaxe',
  'stone_pickaxe','iron_pickaxe','furnace'. Needs crafting_table nearby for 3x3 recipes.
- smelt() needs a furnace nearby (place one first if missing) + fuel in inventory.
- Keep code a SIMPLE straight sequence of await calls. No functions, no loops, no complex logic.

Examples:
- collect 3 cobblestone:  await collect('stone', 3);
- craft stone pickaxe:    await craft('stone_pickaxe', 1);
- smelt iron:             await smelt('raw_iron', 'coal', 3);"""

_FENCE = re.compile(r"```(?:js|javascript)?\s*\n?(.*?)```", re.S)


@dataclass
class GenerationResult:
    """迭代提示的结果。"""

    success: bool
    code: str = ""
    rounds: int = 0
    error: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)


def strip_fences(text: str) -> str:
    """剥离 LLM 可能包裹的 ```js ... ``` 代码块。"""
    m = _FENCE.search(text)
    return m.group(1).strip() if m else text.strip()


async def _llm_chat(llm: Any, messages: list[dict]) -> str:
    resp = await llm.chat(messages=messages)
    return resp.content if hasattr(resp, "content") else str(resp)


async def generate_with_iteration(
    task: str,
    success_criteria: list[str],
    run_code: Any,
    llm: Any,
    *,
    max_iters: int = 4,
    relevant_skills: list[Skill] | None = None,
) -> GenerationResult:
    """论文迭代提示主循环。

    Args:
        task: 自然语言任务（如「造一把铁剑」）
        success_criteria: 验证用后置条件（如 ["has_iron_sword >= 1"]）
        run_code: async callable ``code -> {"status": "success"|"error", "result": ...}``
            实际接 ``bridge.send_command("eval_code", {"code": code})``
        llm: LLM service（.chat(messages=...) -> {.content}）
        max_iters: 论文规定的 ≤4 轮重写上限
        relevant_skills: 检索到的相关 verified 技能（注入 prompt 作参考）
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    skill_hint = ""
    if relevant_skills:
        skill_hint = "\n\nReference skills (similar solved tasks):\n" + "\n".join(
            f"- {s.name}: {s.description}" for s in relevant_skills[:3]
        )

    messages.append(
        {
            "role": "user",
            "content": f"Task: {task}\nSuccess criteria: {success_criteria}{skill_hint}\n\nOutput the JS code:",
        }
    )

    last_error = ""
    code = ""
    history: list[dict[str, Any]] = []

    for i in range(1, max_iters + 1):
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Previous code failed with error:\n{last_error}\n\n"
                        "Analyze the failure and output corrected code."
                    ),
                }
            )

        try:
            raw = await _llm_chat(llm, messages)
        except Exception as exc:
            return GenerationResult(
                success=False, code=code, error=f"LLM call failed: {exc}", rounds=i - 1, history=history
            )

        code = strip_fences(raw)
        history.append({"round": i, "code": code, "error": last_error})
        messages.append({"role": "assistant", "content": raw})

        result = await run_code(code)
        if isinstance(result, dict) and result.get("status") == "success":
            logger.info(f"[CodeGen] task '{task}' succeeded in round {i}/{max_iters}")
            return GenerationResult(success=True, code=code, rounds=i, history=history)

        last_error = (
            str(result.get("result", "unknown error"))
            if isinstance(result, dict)
            else str(result)
        )
        logger.warning(f"[CodeGen] round {i}/{max_iters} failed: {last_error[:200]}")

    logger.error(f"[CodeGen] task '{task}' exhausted {max_iters} iterations")
    return GenerationResult(success=False, code=code, error=last_error, rounds=max_iters, history=history)


def to_skill(
    task: str,
    result: GenerationResult,
    *,
    preconditions: list[str] | None = None,
    postconditions: list[str] | None = None,
    skill_id: str = "",
) -> Skill:
    """把成功的 GenerationResult 转成 code-body Skill（validated=False，待 verifier 验证）。"""
    return Skill(
        id=skill_id or f"voyager_{uuid.uuid4().hex[:10]}",
        name=task[:60],
        description=f"Voyager-generated skill: {task}",
        category="learned",
        preconditions=preconditions or [],
        body={
            "type": "code",
            "code": result.code,
            "api_version": "v1",
            "timeout": 180.0,
        },
        postconditions=postconditions or [],
        tags=["voyager", "learned", "code-body"],
        validated=False,
        success_count=1,
    )
