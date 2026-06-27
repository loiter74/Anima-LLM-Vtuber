"""Automatic curriculum (mc-bot-voyager-learning T6).

论文自动课程：LLM 根据当前 inventory / 技术树位置 / 已学技能 / 已完成已失败任务，
出"下一个合适难度、未完成、朝终极目标(iron_pickaxe)推进"的任务。

半开放：限定生存技术树（采集/冶炼/工具/建造），靠 LLM 的 MC 世界知识做难度匹配。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

CURRICULUM_SYSTEM_PROMPT = """You are a Minecraft automatic curriculum teacher for a bot.

Given the bot's current state, propose the NEXT task that is:
- NOT too hard for current equipment (respect the tech tree)
- NOT already completed
- Progressing toward the ultimate goal: craft an iron_pickaxe
- Within scope: collection / crafting / smelting / mining only

Tech tree: punch wood -> wood tools -> stone tools -> (mine iron_ore + coal) -> smelt iron_ingot -> iron tools.

Output ONLY a JSON object, no markdown fences:
{"task": "one-sentence concrete task using available API", "success_criteria": ["has_<item> >= N"], "reasoning": "one short sentence"}

Task must be achievable by JS code calling ONLY: collect(block_type,count), craft(recipe,count), smelt(item,fuel,count), goto(x,y,z), place(block_type,x,y,z), status(), waitFor(sec).
Prefer tasks that directly advance the iron_pickaxe tech tree. Keep tasks small and verifiable by inventory checks."""

_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.S)


@dataclass
class CurriculumTask:
    task: str
    success_criteria: list[str] = field(default_factory=list)
    reasoning: str = ""


def _extract_json(text: str) -> dict[str, Any]:
    t = text.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(t)
    if m:
        return json.loads(m.group(1).strip())
    raise ValueError(f"no JSON in LLM response: {t[:200]}")


def _tier_of(inventory: dict[str, int]) -> str:
    if inventory.get("iron_pickaxe", 0) >= 1:
        return "iron"
    if inventory.get("stone_pickaxe", 0) >= 1:
        return "stone"
    if inventory.get("wooden_pickaxe", 0) >= 1:
        return "wood"
    return "empty"


async def next_task(
    llm: Any,
    state: dict[str, Any],
    completed: list[str],
    failed: list[str],
    learned_skills: list[str],
) -> CurriculumTask:
    """向 LLM 求下一个任务。"""
    inv = state.get("inventory", {})
    user = (
        f"Current inventory: {inv}\n"
        f"Equipment tier: {_tier_of(inv)}\n"
        f"Completed tasks (recent last): {completed[-15:]}\n"
        f"Recently failed (avoid repeating): {failed[-8:]}\n"
        f"Learned/verified skills: {learned_skills[:20]}\n"
        f"Position: {state.get('position')}, health: {state.get('health')}, food: {state.get('food')}\n\n"
        f"Ultimate goal: craft an iron_pickaxe. Propose the next task. Output JSON only."
    )
    messages = [
        {"role": "system", "content": CURRICULUM_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    resp = await llm.chat(messages=messages)
    content = resp.content if hasattr(resp, "content") else str(resp)
    data = _extract_json(content)
    return CurriculumTask(
        task=str(data.get("task", "")).strip(),
        success_criteria=list(data.get("success_criteria", []) or []),
        reasoning=str(data.get("reasoning", "")),
    )
