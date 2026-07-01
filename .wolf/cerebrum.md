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
- [2026-06-28] **T9 学习闭环接线 = 重构+复用（非子进程/非重写）**：`self_evolution.main()` 循环体抽成可复用 `run_learning_loop(bridge,lib,llm) -> summary`；`bridge._start_autonomous()` 按 mode 分支（LEARN+LLM → 后台 task 跑 run_learning_loop；LIVE/fallback/无 LLM → 规则 AutonomousLoop）。`set_voyager_mode` 在 bridge 已运行时按需启停学习 task。选此而非「子进程拉起脚本」（IPC 重、状态隔离）或「最小缝隙」（不自动跑），因复用已测核心、wiring 逻辑可 mock 测试。运行验证仍需实机（T15 @slow）。

## Key Learnings (continued)

- **SkillLibrary.cleanup() 只清 is_learned=True 的低质技能**（`success_rate<0.3 and total>=10`）。Voyager code-body skill（`to_skill()` 产出、`self_evolution` 直接 `save_skill`）默认 `is_learned=False`，故 cleanup() 永远不会淘汰它们。要淘汰这类技能需用 `fail_count` 阈值 + 直接 `remove_skill()`（见 `other/purify.py` 的 `_EVICT_FAIL_THRESHOLD=3`）。
- **voyager 假技能污染根因**：`self_evolution` 曾在 verify 前用 `_rcon give` 补全 inventory，使确定性闸误判 `validated=True`。现由 `MC_EVO_ALLOW_GIVE`（默认 False）开关守卫 + `purify` 历史复验修复（OpenSpec `mc-evo-purity`）。
- **Voyager 阶段架构（mc-bot-voyager-learning）**：`config.mode` = `MinecraftMode` 枚举（learn/live/fallback）。学习期 4 组件 = `curriculum.py` 出题 + `skill/code_generator.py` 迭代生成 mineflayer JS + `bot/index.js::eval_code` 受控沙箱 + `skill/verifier.py` 确定性+LLM 双闸。完整学习循环以独立脚本形式在 `other/self_evolution.py::main()`（自带 bridge），**尚未接进 `bridge._start_autonomous()`**（T9，待实机验证）。直播期 = `autonomous/live_agent.py::LiveAgent` 只复用 `validated` 技能不生成代码；失败 K 次（`degrade_threshold=3`）降权 `validated=False`；无适配技能/全失败 → 回落 `SurvivalIronRunner`。
- **训练充分判据（三选一）**：`autonomous/training.py::TrainingTracker` —— ① 技术树覆盖≥80%（`benchmark.criteria.TECH_TREE_KEY_ITEMS`：木/石/铁/钻石镐 + 工作台 + 熔炉）② 近 N 任务成功率≥70%（需攒满窗口样本）③ unique 物品发现数≥阈值。任一达标即可 learn→live（`AutonomousLoop._check_training_sufficient`）。
- **SkillLibrary 直播检索**：`match_skills(context)` 已按 precondition 过滤 + `success_rate` 排序；`LiveAgent.select_skill` 在其上再过滤 `validated` + 按 goal 关键词相关度细化。

## Do-Not-Repeat (continued)

- [2026-06-28] **跑 pytest 前先覆盖 addopts**：`pyproject.toml` 的 `addopts` 引用了 `pytest-xdist`(`-n`) 和 `pytest-timeout`(`--timeout`)，但当前 hermes venv 未装这两个插件，直接 `python -m pytest` 会报 `unrecognized arguments`。务必用 `PYTHONPATH=src python -m pytest -o addopts="" -p no:cacheprovider ...` 运行测试。
- [2026-06-28] **bot 目录用 ESM（package.json "type":"module"）**：`src/animetta/tools/minecraft/bot/` 下所有 `.js` 必须用 `import`/`export`，不能用 CommonJS 的 `require`/`module.exports`。后者在该目录会被当 ESM 解析，`module` 未定义 → 静默导出空对象 `{}`（require 不抛、返回空），极难排查。新增 bot 侧 JS 模块一律 ESM；测试用 `node --input-type=module -e` 或 `.test.js`(import) 跑。
- [2026-06-28] **勿让 ruff 删 `tools.py` 的 `import asyncio`**：`core/tools.py` 里 `import asyncio` 对运行代码是「未使用」的，但 `tests/tools/minecraft/core/test_bridge.py` 用 `patch("...tools.asyncio.get_running_loop")` 把它当 patch 锚点。`ruff --fix` 会按 F401 删除它导致测试红。必须保留并以 `# noqa: F401` 标注（见 bug-081）。改 tools.py 后务必跑该测试。
