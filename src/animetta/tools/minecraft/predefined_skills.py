"""
Predefined Skills — Starter skill library for MC Bot Voyager

Provides 9 fundamental skills: 6 for survival/collection/building + 3 for crafting.
"""

from .skill_library import Skill, SkillStep


def _make_survival_food() -> Skill:
    """找食物 — 找到并收集食物来源"""
    return Skill(
        id="survival_food",
        name="找食物",
        description="当食物不足时，寻找并击杀动物获取肉食",
        category="survival",
        preconditions=["food < 15"],
        steps=[
            SkillStep(name="check", params={"condition": "food < 15"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="collect", params={"block_type": "beef|pork|chicken", "count": 3}),
        ],
        postconditions=["food > 15"],
        tags=["survival", "food", "eat", "hungry"],
    )


def _make_survival_shelter() -> Skill:
    """建庇护所 — 夜间建造简易庇护所"""
    return Skill(
        id="survival_shelter",
        name="建庇护所",
        description="夜间建造简易石头庇护所以确保安全",
        category="survival",
        preconditions=["is_night", "health > 6"],
        steps=[
            SkillStep(name="check", params={"condition": "is_night"}),
            SkillStep(name="check", params={"condition": "health > 6"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 64, "z": 0}),
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 1, "y": 64, "z": 0}),
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 64, "z": 1}),
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 1, "y": 64, "z": 1}),
            SkillStep(name="place", params={"block_type": "oak_planks", "x": 0, "y": 65, "z": 0}),
            SkillStep(name="place", params={"block_type": "oak_planks", "x": 1, "y": 65, "z": 0}),
            SkillStep(name="place", params={"block_type": "oak_planks", "x": 0, "y": 65, "z": 1}),
            SkillStep(name="place", params={"block_type": "oak_planks", "x": 1, "y": 65, "z": 1}),
        ],
        postconditions=["has_shelter"],
        tags=["survival", "shelter", "night", "safety"],
    )


def _make_collect_mine() -> Skill:
    """挖矿 — 采集石头和圆石"""
    return Skill(
        id="collect_mine",
        name="挖矿",
        description="前往洞穴或石头区域挖掘圆石",
        category="collection",
        preconditions=["has_pickaxe"],
        steps=[
            SkillStep(name="check", params={"condition": "has_pickaxe"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="mine", params={"block_type": "stone|cobblestone", "count": 16}),
            SkillStep(name="collect", params={"block_type": "cobblestone", "count": 16}),
        ],
        postconditions=["has_cobblestone"],
        tags=["collection", "mine", "stone", "cobblestone"],
    )


def _make_collect_wood() -> Skill:
    """伐木 — 砍伐树木获取原木"""
    return Skill(
        id="collect_wood",
        name="伐木",
        description="找到树木并砍伐获取原木",
        category="collection",
        preconditions=["health > 6"],
        steps=[
            SkillStep(name="check", params={"condition": "health > 6"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="mine", params={"block_type": "oak_log", "count": 8}),
            SkillStep(name="collect", params={"block_type": "oak_log", "count": 8}),
        ],
        postconditions=["has_oak_log"],
        tags=["collection", "wood", "log", "tree"],
    )


def _make_build_house() -> Skill:
    """建房子 — 建造简易石头木屋"""
    return Skill(
        id="build_house",
        name="建房子",
        description="使用圆石和木板建造简易房屋",
        category="building",
        preconditions=["has_cobblestone >= 32", "has_oak_log >= 16"],
        steps=[
            SkillStep(name="check", params={"condition": "has_cobblestone >= 32"}),
            SkillStep(name="check", params={"condition": "has_oak_log >= 16"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            # Foundation — 5x5 cobblestone
            *[
                SkillStep(name="place", params={"block_type": "cobblestone", "x": x, "y": 64, "z": z})
                for z in range(5)
                for x in range(5)
            ],
            # Walls — 5x5 oak_planks at y=65
            *[
                SkillStep(name="place", params={"block_type": "oak_planks", "x": x, "y": 65, "z": z})
                for z in range(5)
                for x in range(5)
            ],
            # Roof — 5x5 oak_planks at y=66
            *[
                SkillStep(name="place", params={"block_type": "oak_planks", "x": x, "y": 66, "z": z})
                for z in range(5)
                for x in range(5)
            ],
        ],
        postconditions=["has_house"],
        tags=["building", "house", "home"],
    )


def _make_build_wall() -> Skill:
    """建围墙 — 建造防御围墙"""
    return Skill(
        id="build_wall",
        name="建围墙",
        description="使用圆石建造围墙",
        category="building",
        preconditions=["has_cobblestone >= 16"],
        steps=[
            SkillStep(name="check", params={"condition": "has_cobblestone >= 16"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            *[
                SkillStep(name="place", params={"block_type": "cobblestone", "x": x, "y": 64, "z": 0})
                for x in range(16)
            ],
        ],
        postconditions=["has_wall"],
        tags=["building", "wall", "fence"],
    )


def _make_craft_equipment() -> Skill:
    """造装备 — 根据可用材料制造最佳工具和全套装备"""
    return Skill(
        id="craft_equipment",
        name="造装备",
        description="根据现有材料制造最佳工具和全套装备",
        category="crafting",
        preconditions=["has_oak_log >= 3"],
        steps=[
            SkillStep(name="check", params={"condition": "has_oak_log >= 3"}),
            SkillStep(name="craft", params={"recipe": "stick", "count": 4}),
            SkillStep(name="craft", params={"recipe": "wooden_pickaxe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "stone_pickaxe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_pickaxe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "diamond_pickaxe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_axe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_sword", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_helmet", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_chestplate", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_leggings", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_boots", "count": 1}),
        ],
        postconditions=["has_tools"],
        tags=["crafting", "equipment", "tools", "armor", "gear"],
    )


def _make_craft_basic_tools() -> Skill:
    """造基础工具 — 只制造最基础的木制工具"""
    return Skill(
        id="craft_basic_tools",
        name="造基础工具",
        description="只制造最基础的木制工具",
        category="crafting",
        preconditions=["has_oak_log >= 3"],
        steps=[
            SkillStep(name="check", params={"condition": "has_oak_log >= 3"}),
            SkillStep(name="craft", params={"recipe": "stick", "count": 2}),
            SkillStep(name="craft", params={"recipe": "wooden_pickaxe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "wooden_axe", "count": 1}),
            SkillStep(name="craft", params={"recipe": "wooden_sword", "count": 1}),
        ],
        postconditions=["has_basic_tools"],
        tags=["crafting", "tools", "basic", "wood"],
    )


def _make_craft_armor() -> Skill:
    """造盔甲 — 制造铁质盔甲套装"""
    return Skill(
        id="craft_armor",
        name="造盔甲",
        description="制造铁质盔甲套装提供防护",
        category="crafting",
        preconditions=["has_iron_ingot >= 24"],
        steps=[
            SkillStep(name="check", params={"condition": "has_iron_ingot >= 24"}),
            SkillStep(name="craft", params={"recipe": "iron_helmet", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_chestplate", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_leggings", "count": 1}),
            SkillStep(name="craft", params={"recipe": "iron_boots", "count": 1}),
        ],
        postconditions=["has_armor"],
        tags=["crafting", "armor", "iron", "defense"],
    )


def get_predefined_skills() -> list[Skill]:
    """Return all predefined skills."""
    return [
        _make_survival_food(),
        _make_survival_shelter(),
        _make_collect_mine(),
        _make_collect_wood(),
        _make_build_house(),
        _make_build_wall(),
        _make_craft_equipment(),
        _make_craft_basic_tools(),
        _make_craft_armor(),
    ]
