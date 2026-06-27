"""Voyager 风格 code-body 技能种子（mc-bot-voyager-learning）。

与 predefined.py 的 steps-based 技能并存：这里 ``body.type == "code"``，存的是
可被 ``eval_code`` 沙箱执行的 JS 代码（论文 Voyager 的技能形态）。

code 基于 Survival Runner 实测有效的动作序列，因此 ``validated=True``——
这是「学习期产出的 verified 技能」的 bootstrap 种子形态。
"""
from __future__ import annotations

from .models import Skill


def _make_craft_wooden_pickaxe_code() -> Skill:
    """造木镐（code-body）—— 从空手到木镐的完整 JS。

    动作对齐 survival runner 的 WOOD→CRAFTING_TABLE→WOODEN_PICKAXE 阶段
    与 predefined.craft_wooden_pickaxe（cerebrum 记录 wooden_pickaxe 实测 OK）。
    只用受限 API（collect/craft/status），不碰 bot/require/process。
    """
    code = "\n".join(
        [
            "// Voyager code-body skill: craft a wooden pickaxe from scratch",
            "await collect('oak_log', 5);",
            "await craft('oak_planks', 4);",
            "await craft('crafting_table', 1);",
            "await craft('stick', 4);",
            "await craft('wooden_pickaxe', 1);",
            "const s = await status();",
            "return 'wooden_pickaxe=' + (s.inventory['wooden_pickaxe'] || 0);",
        ]
    )
    return Skill(
        id="voyager_craft_wooden_pickaxe",
        name="造木镐(Voyager代码)",
        description="Voyager 风格 code-body 技能：空手→原木→木板→工作台→木棍→木镐",
        category="crafting",
        preconditions=["health > 6"],
        body={
            "type": "code",
            "code": code,
            "api_version": "v1",
            "timeout": 180.0,
        },
        postconditions=["has_wooden_pickaxe >= 1"],
        tags=["crafting", "wooden_pickaxe", "voyager", "code-body", "phase2"],
        validated=True,
        success_count=1,
        fail_count=0,
    )


def get_code_seeds() -> list[Skill]:
    """返回所有 Voyager code-body 种子技能（学习期 verified 产物的 bootstrap 形态）。"""
    return [
        _make_craft_wooden_pickaxe_code(),
    ]
