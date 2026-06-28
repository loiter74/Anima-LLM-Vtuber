# Minecraft 生存技能流程总结

> 2026-06-26 实测验证。iron_pickaxe=1 已成功。

## 技术树总览

```
伐木 → 木板 → 工作台 → 木棍 → 木镐
  ↓
挖石头(圆石) → 石镐 → 石剑 + 熔炉
  ↓
挖煤矿 → 挖铁矿 → 冶炼铁锭
  ↓
铁镐 + 铁剑 + 铁胸甲
```

## Phase 1: WOOD (伐木)

| 动作 | 数量 | 结果 |
|------|------|------|
| collect oak_log | 3-5 | 获得原木 |

**关键点：**
- `bot.dig()` 只破坏方块，掉落物需要 `_pickupDroppedItems()` 拾取
- auto-eat/combat 会中断挖掘，已通过 `disableAuto()` 解决
- 挖掘被中断时自动重试（最多3次）
- 如果附近没有树，`_explore_for_block()` 会随机走动探索

## Phase 2: CRAFTING_TABLE (工作台)

| 动作 | 材料 | 结果 |
|------|------|------|
| craft oak_planks ×4 | 1 oak_log | 4 橡木板 |
| craft crafting_table ×1 | 4 oak_planks | 1 工作台 |

**关键点：**
- Minecraft 1.21.4 有多种木板变体（oak, pale_oak, cherry 等）
- `bot.recipesFor()` 只返回库存能制作的配方，可能返回空
- 使用 `FALLBACK_RECIPES` 硬编码配方作为后备
- 2x2 配方（木板、木棍）不需要工作台，直接在背包制作

## Phase 3: WOODEN_PICKAXE (木镐)

| 动作 | 材料 | 结果 |
|------|------|------|
| craft stick ×4 | 2 oak_planks | 4 木棍 |
| craft wooden_pickaxe ×1 | 3 oak_planks + 2 stick | 1 木镐 |

**关键点：**
- 3x3 配方需要工作台
- `_ensureCraftingTable()` 自动在附近寻找或放置工作台
- 放置工作台时搜索周围 solid block，不只检查脚下
- `bot.craft()` 打开工作台窗口有 20 秒超时

## Phase 4: COBBLESTONE (圆石)

| 动作 | 数量 | 结果 |
|------|------|------|
| collect stone | 6-12 | 获得圆石 |

**关键点：**
- 石头在 y<64 的地下，bot 在高山生物群系可能找不到
- `_explore_for_block()` 对地下矿物会自动向下挖几格
- 挖 stone block 会掉落 cobblestone（物品名≠方块名）
- `ITEM_TO_BLOCK` 映射：cobblestone → stone

## Phase 5: STONE_KIT (石质装备)

| 动作 | 材料 | 结果 |
|------|------|------|
| craft stone_pickaxe ×1 | 3 cobblestone + 2 stick | 1 石镐 |
| craft stone_sword ×1 | 2 cobblestone + 1 stick | 1 石剑 |
| craft furnace ×1 | 8 cobblestone | 1 熔炉 |

## Phase 6-9: IRON PATH (铁质装备)

| Phase | 动作 | 说明 |
|-------|------|------|
| FUEL | collect coal_ore ×3 | 挖煤矿获得煤炭 |
| IRON_ORE | collect iron_ore ×3 | 挖铁矿获得生铁 |
| SMELT_IRON | smelt raw_iron ×3 | 用煤炭冶炼铁锭 |
| IRON_GEAR | craft iron_pickaxe 等 | 制作铁质装备 |

## 已知问题

### "Digging aborted" (~20%概率)
- 原因：auto-eat/combat 虽已禁用，仍有不明原因中断
- 缓解：3次自动重试，大部分情况能恢复

### Bot 在高山/海洋生物群系找不到资源
- 原因：y>100 没有石头，海洋没有树
- 缓解：`_explore_for_block()` 向下挖掘 + 随机走动

### "Bot busy, command rejected"
- 原因：上一个命令未完成时发送新命令
- 缓解：重试时等待 3 秒

## 关键修复记录

| 修复 | 文件 | 影响 |
|------|------|------|
| 物品拾取 | bot/index.js | `_pickupDroppedItems()` 挖掘后自动拾取 |
| 配方兼容 | bot/index.js | `FALLBACK_RECIPES` 兼容 1.21.4 多木板变体 |
| 自动行为暂停 | bot/index.js | `disableAuto()`/`enableAuto()` 防止挖掘中断 |
| 地下探索 | bot/index.js | `_explore_for_block()` 对矿物自动向下挖 |
| 结构化错误 | bot/index.js | `craftError()` 让恢复系统正确分派 |
| 方块类型修复 | recovery.py | coal→coal_ore, raw_iron→iron_ore |

## 使用方式

```python
# LLM 工具调用
mc_survival_iron()  # 一键运行完整铁装备流程

# 或分步调用
mc_collect("oak_log", 3)
mc_craft("oak_planks", 4)
mc_craft("crafting_table", 1)
# ...
```

## Voyager Skill 系统

项目实现了 Voyager 论文风格的技能学习系统。技能存储在 `data/mc_skills.db` SQLite 数据库中。

### 已注册的技能（13个）

| ID | 名称 | 类别 | 阶段 | 步骤数 |
|----|------|------|------|--------|
| `collect_wood` | 伐木 | collection | 1 | 1 |
| `craft_wooden_pickaxe` | 造木镐 | crafting | 2 | 5 |
| `craft_stone_pickaxe` | 造石镐 | crafting | 3 | 4 |
| `craft_iron_pickaxe` | 造铁镐 | crafting | 4 | 6 |
| `survival_iron_pickaxe` | 生存铁镐 | survival | all | 11 |
| `survival_food` | 找食物 | survival | — | 3 |
| `survival_shelter` | 建庇护所 | survival | — | 11 |
| `collect_mine` | 挖矿 | collection | — | 4 |
| `build_house` | 建房子 | building | — | 78 |
| `build_wall` | 建围墙 | building | — | 18 |
| `craft_equipment` | 造装备 | crafting | — | 12 |
| `craft_basic_tools` | 造基础工具 | crafting | — | 5 |
| `craft_armor` | 造盔甲 | crafting | — | 5 |

### 技能前置条件链

```
collect_wood (health > 6)
  → craft_wooden_pickaxe (has_oak_log >= 3)
    → craft_stone_pickaxe (has_wooden_pickaxe, has_stick >= 2)
      → craft_iron_pickaxe (has_stone_pickaxe, has_stick >= 2)
```

### SkillStep 类型

`goto`, `smart_goto`, `collect`, `mine`, `place`, `smart_build`, `craft`, `smelt`, `chat`, `check`, `wait`, `attack`

### 自主学习流程

1. 自主循环执行动作 → TraceRecorder 记录 trace
2. 成功后 → SkillExtractor (LLM) 提取 skill
3. SkillValidator 三阶段验证 (schema → action → simulation)
4. SkillLibrary.add_learned() 去重 + 存入 SQLite
5. 后续 tick → match_skills(context) 匹配并执行
