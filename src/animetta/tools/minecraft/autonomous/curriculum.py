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

CURRICULUM_SYSTEM_PROMPT = """You are a Minecraft automatic curriculum teacher for a bot.

Given the bot's current state, propose the NEXT task that is:
- NOT too hard for current equipment (respect the tech tree)
- NOT already completed
- Progressing toward the ultimate goal: craft ANY ONE golden armor piece (golden_helmet OR golden_chestplate OR golden_leggings OR golden_boots) by gathering ALL resources yourself. Bot already has iron armor — upgrade one slot to gold.
- ALSO maximize discovery of NEW craftable items (when the main goal is blocked, propose tasks that discover items the bot has never held)
- Within scope: collection / crafting / smelting / mining / equipping

Tech tree: wood tools (collect('oak_log') then craft wooden_pickaxe) -> stone tools (collect('stone') drops cobblestone, craft stone_pickaxe) -> iron tools (mine iron_ore, smelt raw_iron, craft iron_pickaxe) -> mine gold_ore deep underground (y<32, needs iron_pickaxe) + mine coal_ore for fuel -> smelt('raw_gold','coal',N) -> gold_ingot -> golden armor.
Golden armor costs (gold_ingot each): golden_boots=4, golden_helmet=5, golden_leggings=7, golden_chestplate=8. Prefer the cheapest reachable piece unless inventory already points to another piece.
CRITICAL: the bot MUST gather every resource itself via collect/craft/smelt. Resources do NOT appear by themselves — walk to find oak trees, dig underground for stone then coal_ore/iron_ore/gold_ore (gold_ore is deepest, y<32, often near lava/deepslate). Never assume an item is already available; if the bot lacks something, the task must collect or craft it first.
PREREQUISITE CHAIN: mining gold_ore requires iron_pickaxe. If inv has NO iron_pickaxe, the NEXT task MUST be 'craft iron_pickaxe' (3 iron_ingot + 2 stick at crafting_table) — do NOT propose mining gold_ore until iron_pickaxe exists. If inv lacks iron_ingot/stick, gather those first (smelt raw_iron / craft stick from planks). Always check prerequisites before proposing a mining task.
NEVER REDUNDANT: if inv already has iron_pickaxe, NEVER propose 'craft iron_pickaxe' — instead propose mining (gold_ore to get raw_gold), smelting (raw_gold + coal -> gold_ingot), or crafting any one golden armor piece. Check inv carefully before proposing any craft task to avoid repeats.

Output ONLY a JSON object, no markdown fences:
{"task": "one-sentence concrete task", "success_criteria": ["has_<item> >= N"], "reasoning": "one short sentence"}

Task must be achievable by JS code calling ONLY: collect(block_type,count), craft(recipe,count), smelt(item,fuel,count), equip(item,destination), goto(x,y,z), place(block_type,x,y,z), status(), waitFor(sec).
Keep tasks small + verifiable by inventory checks. If the gold path is blocked (e.g. no gold_ore reachable), pivot to discovering other new craftable items (different tools, blocks, food) to maximize exploration."""

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
        f"Ultimate goal: craft any one golden armor piece BY GATHERING ALL RESOURCES YOURSELF (no free items). Bot already has iron armor — now mine gold_ore deep (y<32) + smelt + craft one golden armor item. Propose the next task. Output JSON only."
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
