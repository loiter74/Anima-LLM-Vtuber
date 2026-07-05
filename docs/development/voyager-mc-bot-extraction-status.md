# Voyager MC Bot Extraction Status

Date: 2026-07-04

## Current State

The Mineflayer runtime has been moved out of Anima into:

- `C:/Users/30262/Project/voyager-mc-bot`

Anima now launches that runtime through `MinecraftBridge` using the generic game-bot stdio transport in `src/animetta/tools/gamebot/`.

## Migrated Responsibilities

- Node.js Mineflayer runtime startup and command handlers live in `C:/Users/30262/Project/voyager-mc-bot/src/index.js`.
- Node-side behavior helpers, initial loadout, smelting, mining, spectator support, and client-viewer support live in the external runtime project.
- **`survival_iron` command** — deterministic wood-to-iron-gear runner is now implemented in `voyager-mc-bot/src/survival/` with phase definitions, inventory helpers, report builders, and runner orchestration. Anima's `mc_survival_iron` delegates through `_send("survival_iron", ...)` with no Python survival imports.
- Voyager mode switching (`set_voyager_mode`) is handled by the external runtime.
- Runtime dependencies and Node tests live in the external `package.json` / `tests/` tree.
- Anima's `config/tools.yaml` points Minecraft runtime settings to the external project.

## Retained Anima Responsibilities

- Generic contracts, client, and stdio transport: `src/animetta/tools/gamebot/`.
- Minecraft compatibility adapter and LangChain tool surface: `src/animetta/tools/minecraft/core/`.
- Socket.IO integration, config loading, viewer event forwarding, and state collection.
- Python-side Minecraft orchestration that has not yet been replaced by external runtime commands:
  - `src/animetta/tools/minecraft/autonomous/`
  - `src/animetta/tools/minecraft/survival/`
  - `src/animetta/tools/minecraft/skill/`
  - `src/animetta/tools/minecraft/tech_tree/`
  - `src/animetta/tools/minecraft/benchmark/`

## Verified Evidence

- `python -m pytest -o addopts='' tests/tools/gamebot tests/tools/minecraft/core/test_bridge.py tests/tools/minecraft/core/test_config.py -q` passes.
- `ruff check src/animetta/tools/gamebot src/animetta/tools/minecraft/core tests/tools/gamebot tests/tools/minecraft/core` passes.
- `npm test` passes in `C:/Users/30262/Project/voyager-mc-bot`.
- `npm run check` passes in `C:/Users/30262/Project/voyager-mc-bot`.
- Real-server smoke using `config/tools.yaml` starts `AnimettaBot`, receives `login` and `spawn`, returns successful `status` and `inventory`, runs `spectate`, and stops cleanly.
- Real-server smoke verifies `set_voyager_mode` for `learn` and `live` is handled by the external runtime.

## Known Residual Work

- The external runtime does not yet own Python-side Voyager goal execution, learning loop implementation, skill library, benchmark, or tech-tree orchestration.
- `voyager_live_goal` is registered in the external runtime and returns a structured `EXTERNAL_VOYAGER_GOAL_NOT_IMPLEMENTED` error until goal execution is migrated.
- Until replacement external commands are implemented and verified, Anima still imports Minecraft-specific Python product modules.
- The `physicTick` warning comes from current third-party dependencies (`mineflayer-pvp` / `mineflayer-statemachine`), not Anima or external runtime source code.
- `C:/Users/30262/Project/voyager-mc-bot` is initialized as its own git repository; files are ready for an initial standalone commit.

## Next Extraction Phase

To make Anima keep only the compatibility adapter plus generic game-bot layer, move these capabilities behind external runtime commands and keep Anima as a command client:

1. ~~`survival_iron`~~ ✅ Done — migrated to `voyager-mc-bot/src/survival/` (2026-07-04)
2. `run_skill`
3. `learn_skill`
4. `benchmark`
5. `tech_tree_step`
6. `voyager_live_goal`

Each command needs contract tests in `voyager-mc-bot`, adapter tests in Anima, and one real-server smoke checkpoint before deleting the corresponding Anima-side implementation.
