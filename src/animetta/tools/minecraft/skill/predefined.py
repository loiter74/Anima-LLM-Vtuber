"""
Predefined Skills — Starter skill library for MC Bot Voyager

Provides fundamental skills organized as a composable tech tree:
  collect_wood → craft_wooden_pickaxe → craft_stone_pickaxe → craft_iron_pickaxe
Each skill can be executed standalone or composed into the full progression.
"""

from .library import Skill, SkillStep

# ---------------------------------------------------------------------------
# Phase 1: Collection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 2: Basic Crafting (no crafting table needed for planks/sticks)
# ---------------------------------------------------------------------------


def _make_craft_wooden_pickaxe() -> Skill:
    """造木镐 — 从原木到木镐的完整流程

    Steps: 原木→木板→工作台→木棍→木镐
    包含自动放置工作台的逻辑。
    """
    return Skill(
        id="craft_wooden_pickaxe",
        name="造木镐",
        description="从原木开始，制作木板、工作台、木棍，最终造出木镐",
        category="crafting",
        preconditions=["has_oak_log >= 3", "health > 6"],
        steps=[
            SkillStep(name="check", params={"condition": "has_oak_log >= 3"}),
            # Craft planks (2x2, no table needed)
            SkillStep(name="craft", params={"recipe": "oak_planks", "count": 4}),
            # Craft crafting table (2x2, no table needed)
            SkillStep(name="craft", params={"recipe": "crafting_table", "count": 1}),
            # Craft sticks (2x2)
            SkillStep(name="craft", params={"recipe": "stick", "count": 4}),
            # Craft wooden pickaxe (3x3, needs table — auto-placed)
            SkillStep(name="craft", params={"recipe": "wooden_pickaxe", "count": 1}, retry=2),
        ],
        postconditions=["has_wooden_pickaxe"],
        tags=["crafting", "tools", "wood", "pickaxe", "phase2"],
    )


# ---------------------------------------------------------------------------
# Phase 3: Stone Tools
# ---------------------------------------------------------------------------


def _make_craft_stone_pickaxe() -> Skill:
    """造石镐 — 挖掘石头并制作石镐

    前置：已有木镐。
    Steps: 挖石头→制作石镐。
    """
    return Skill(
        id="craft_stone_pickaxe",
        name="造石镐",
        description="使用木镐挖掘石头，制作石镐",
        category="crafting",
        preconditions=["has_wooden_pickaxe", "has_stick >= 2", "health > 6"],
        steps=[
            SkillStep(name="check", params={"condition": "has_wooden_pickaxe"}),
            SkillStep(name="check", params={"condition": "has_stick >= 2"}),
            # Mine stone (need 3 cobblestone for pickaxe)
            SkillStep(
                name="collect", params={"block_type": "stone", "count": 6}, timeout=180, retry=3
            ),
            # Craft stone pickaxe
            SkillStep(name="craft", params={"recipe": "stone_pickaxe", "count": 1}, retry=2),
        ],
        postconditions=["has_stone_pickaxe"],
        tags=["crafting", "tools", "stone", "cobblestone", "pickaxe", "phase3"],
    )


# ---------------------------------------------------------------------------
# Phase 4: Iron Smelting & Tools
# ---------------------------------------------------------------------------


def _make_craft_iron_pickaxe() -> Skill:
    """造铁镐 — 从石镐到铁镐的完整流程

    前置：已有石镐。
    Steps: 挖煤矿→挖铁矿→冶炼铁锭→制作铁镐。
    """
    return Skill(
        id="craft_iron_pickaxe",
        name="造铁镐",
        description="使用石镐挖煤和铁矿，冶炼铁锭，制作铁镐",
        category="crafting",
        preconditions=["has_stone_pickaxe", "has_stick >= 2", "health > 6"],
        steps=[
            SkillStep(name="check", params={"condition": "has_stone_pickaxe"}),
            SkillStep(name="check", params={"condition": "has_stick >= 2"}),
            # Mine coal ore (fuel for smelting)
            SkillStep(
                name="collect", params={"block_type": "coal_ore", "count": 3}, timeout=120, retry=3
            ),
            # Mine iron ore
            SkillStep(
                name="collect", params={"block_type": "iron_ore", "count": 3}, timeout=180, retry=3
            ),
            # Smelt iron (raw_iron + coal → iron_ingot)
            SkillStep(
                name="smelt",
                params={"item": "raw_iron", "fuel": "coal", "count": 3},
                timeout=120,
                retry=2,
            ),
            # Craft iron pickaxe
            SkillStep(name="craft", params={"recipe": "iron_pickaxe", "count": 1}, retry=2),
        ],
        postconditions=["has_iron_pickaxe"],
        tags=["crafting", "tools", "iron", "smelting", "pickaxe", "phase4"],
    )


# ---------------------------------------------------------------------------
# Full Progression: Empty → Iron Pickaxe
# ---------------------------------------------------------------------------


def _make_survival_iron_pickaxe() -> Skill:
    """生存铁镐 — 从空手到铁镐的完整生存流程

    这是一个复合技能，串联所有阶段：
    伐木→木镐→石镐→煤矿→铁矿→冶炼→铁镐

    对应 mc_survival_iron() 的前半段（到铁镐为止）。
    """
    return Skill(
        id="survival_iron_pickaxe",
        name="生存铁镐",
        description="从空手开始，完成完整的铁镐生存技术树",
        category="survival",
        preconditions=["health > 6"],
        steps=[
            # Phase 1: Wood
            SkillStep(
                name="collect", params={"block_type": "oak_log", "count": 5}, timeout=120, retry=2
            ),
            # Phase 2: Wooden tools
            SkillStep(name="craft", params={"recipe": "oak_planks", "count": 4}),
            SkillStep(name="craft", params={"recipe": "crafting_table", "count": 1}),
            SkillStep(name="craft", params={"recipe": "stick", "count": 4}),
            SkillStep(name="craft", params={"recipe": "wooden_pickaxe", "count": 1}, retry=2),
            # Phase 3: Stone tools
            SkillStep(
                name="collect", params={"block_type": "stone", "count": 6}, timeout=180, retry=3
            ),
            SkillStep(name="craft", params={"recipe": "stone_pickaxe", "count": 1}, retry=2),
            # Phase 4: Iron tools
            SkillStep(
                name="collect", params={"block_type": "coal_ore", "count": 3}, timeout=120, retry=3
            ),
            SkillStep(
                name="collect", params={"block_type": "iron_ore", "count": 3}, timeout=180, retry=3
            ),
            SkillStep(
                name="smelt",
                params={"item": "raw_iron", "fuel": "coal", "count": 3},
                timeout=120,
                retry=2,
            ),
            SkillStep(name="craft", params={"recipe": "iron_pickaxe", "count": 1}, retry=2),
        ],
        postconditions=["has_iron_pickaxe"],
        tags=["survival", "iron", "pickaxe", "full-progression", "tech-tree"],
    )


# ---------------------------------------------------------------------------
# Existing skills (preserved)
# ---------------------------------------------------------------------------


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


def _make_survival_water_bucket_clutch() -> Skill:
    """落地水 — 高空坠落时用水桶抵消摔落伤害"""
    return Skill(
        id="survival_water_bucket_clutch",
        name="落地水",
        description="检测到高跌落风险且背包有水桶时，立刻向脚下放水缓冲落地",
        category="survival",
        preconditions=["fall_risk >= 2", "has_water_bucket"],
        steps=[
            SkillStep(name="check", params={"condition": "fall_risk >= 2"}),
            SkillStep(name="water_bucket_clutch", params={}, timeout=3, retry=1),
        ],
        postconditions=["fall_risk < 2"],
        tags=["survival", "fall", "water_bucket", "clutch", "safety"],
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
                SkillStep(
                    name="place", params={"block_type": "cobblestone", "x": x, "y": 64, "z": z}
                )
                for z in range(5)
                for x in range(5)
            ],
            # Walls — 5x5 oak_planks at y=65
            *[
                SkillStep(
                    name="place", params={"block_type": "oak_planks", "x": x, "y": 65, "z": z}
                )
                for z in range(5)
                for x in range(5)
            ],
            # Roof — 5x5 oak_planks at y=66
            *[
                SkillStep(
                    name="place", params={"block_type": "oak_planks", "x": x, "y": 66, "z": z}
                )
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
                SkillStep(
                    name="place", params={"block_type": "cobblestone", "x": x, "y": 64, "z": 0}
                )
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
        # Collection
        _make_collect_wood(),
        # Crafting — tech tree progression
        _make_craft_wooden_pickaxe(),
        _make_craft_stone_pickaxe(),
        _make_craft_iron_pickaxe(),
        # Full progression
        _make_survival_iron_pickaxe(),
        # Survival
        _make_survival_food(),
        _make_survival_shelter(),
        _make_survival_water_bucket_clutch(),
        # Legacy / standalone
        _make_collect_mine(),
        _make_build_house(),
        _make_build_wall(),
        _make_craft_equipment(),
        _make_craft_basic_tools(),
        _make_craft_armor(),
    ]
