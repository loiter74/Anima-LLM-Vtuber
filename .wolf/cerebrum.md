# Cerebrum

> OpenWolf's learning memory. Updated automatically as the AI learns from interactions.
> Do not edit manually unless correcting an error.
> Last updated: 2026-06-22

## User Preferences

<!-- How the user likes things done. Code style, tools, patterns, communication. -->

## Key Learnings

- **Project:** animetta
- **Description:** <p align="center">
- **Minecraft survival module:** `mc_survival_iron()` runs a 9-phase state machine: wood → crafting_table → wooden_pickaxe → cobblestone → stone_kit → fuel → iron_ore → smelt_iron → iron_gear. Python (runner.py) decides phases; Node.js (index.js) executes atomic actions. Recovery system maps failures to corrective actions.
- **Minecraft crafting:** `_craft()` uses mineflayer's `recipesFor()` API. Needs crafting table for 3x3 recipes. Auto-places crafting table from inventory if none nearby. `_checkCraftMaterials()` validates inventory before crafting.
- **Minecraft block/item duality:** Mining `stone` blocks drops `cobblestone` items. Mining `coal_ore` drops `coal` items. Status reports inventory by item name, not block name. Recovery system must translate between the two.
- **Minecraft item pickup:** `bot.dig(block)` only breaks the block — dropped items are separate entities. Must scan `bot.entities` for `name === 'item'`, navigate to them, and wait for automatic pickup.
- **Minecraft 1.21.4 recipes:** Multiple plank variants (oak, pale_oak, cherry, etc.) cause `recipesFor()` to return empty when the first recipe uses a plank type the bot doesn't have. Use `recipesAll()` + fallback hardcoded recipes.
- **Mineflayer dig interruption:** `bot.dig()` can be aborted by auto-eat (`bot.consume()`), auto-combat (`bot.pvp.attack()`), or pathfinder movement. Disable auto behaviors during critical dig operations.

## Do-Not-Repeat

- [2026-06-26] Minecraft item names ≠ block names. `coal` is an item, `coal_ore` is the block. `cobblestone` is an item (drop), `stone` is the block. Always use block names for `_collect`/`_mine`, use `ITEM_TO_BLOCK` mapping for recovery actions.
- [2026-06-26] Node.js `_craft()` errors must include structured fields (`code`, `missing`, `needsTable`) for Python recovery system to dispatch correct recovery actions. Plain `Error` objects get treated as generic retries.
- [2026-06-26] `bot.dig()` does NOT pick up items. Must add explicit item pickup logic after every dig.
- [2026-06-26] `bot.recipesFor()` is inventory-filtered. In 1.21.4 with multiple plank variants, it returns empty. Use `recipesAll()` or hardcoded fallback recipes.
- [2026-06-26] Auto-eat and auto-combat interrupt `bot.dig()`. Must disable them during collect/mine operations.

## Decision Log

<!-- Significant technical decisions with rationale. Why X was chosen over Y. -->

- [2026-06-27] **mc-bot 当前不是 Voyager 架构**：是「确定性 Survival Runner 状态机 + 基本死代码的 Voyager 侧」。`bridge._start_autonomous()` 从未注入 planner（autonomous loop 实际跑 RulesEngine 硬编码优先级）；`config.py:30` `autonomous: bool` 与 `tools.py:47` `mc_config.autonomous.loop` 不同步，`tools.yaml` 传 `autonomous: true`(bool) 触发 `True.loop` AttributeError，autonomous loop 启动即失败；SkillLibrary 学习分支从未激活；LLM 不生成可执行代码（planner 只产 collect/mine/craft 动作序列 JSON）。Survival Runner 是唯一可靠路径。
- [2026-06-27] **mc-bot Voyager 化方案 = 双阶段架构**（OpenSpec: `mc-bot-voyager-learning`）。学习期离线跑完整 4 组件闭环攒 verified 技能，直播期只复用 verified 技能不生成代码——用时间解耦化解「自由探索 vs 直播稳定」。关键决策：① LLM 生成可执行 mineflayer JS（非 plan）以复现论文迭代提示；② 云强模型（本地 7B 写不出能跑的 JS）；③ 沙箱用受控 eval + 受限 API 表面（vm2 已废弃有 CVE、isolated-vm 难跨 isolate 传 mineflayer）；④ 自我验证确定性+LLM 双重（对论文纯 LLM 的优化）；⑤ Survival Runner 永不删除（bootstrap 种子 + 直播兜底 + fallback）。落地顺序里 T3「最小闭环 spike」是 go/no-go 关卡。
