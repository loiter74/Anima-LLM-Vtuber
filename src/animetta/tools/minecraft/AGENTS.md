# Minecraft Bot Module — Guide for AI Agents

## Module Overview

This module provides the Minecraft gameplay integration for Animetta. It bridges Python (LangGraph/LangChain) with a Node.js Mineflayer bot for real-time Minecraft interaction.

## Architecture

```
Python (LangGraph) ←→ MinecraftBridge ←→ Node.js (Mineflayer) ←→ Minecraft Server
```

- **Python layer**: LangChain @tool functions, survival state machine, skill library, autonomous behavior
- **Bridge**: JSON-line IPC over stdin/stdout subprocess
- **Node.js layer**: Mineflayer bot with pathfinding, combat, auto-eat behaviors

## Key Files

### Core
- `bridge.py` — MinecraftBridge class, subprocess lifecycle, JSON-line protocol
- `tools.py` — 13 LangChain @tool definitions (mc_goto, mc_collect, mc_craft, mc_smelt, mc_status, mc_survival_iron, etc.)
- `config.py` — Pydantic config models

### Survival Iron Run
- `survival_models.py` — SurvivalPhase enum, PhaseResult, RunReport, InventoryGoal
- `survival_inventory.py` — Item alias normalization, goal satisfaction, missing-material calculation
- `survival_recovery.py` — Failure-to-recovery mapping, safety checks (health/food/hostiles)
- `survival_runner.py` — SurvivalIronRunner — the deterministic wood-to-iron-gear state machine
- `survival_benchmark.py` — Run summaries, markdown reports, multi-run comparison

### Skills and Learning
- `skill_library.py` — Facade for SkillLibrary
- `skill_models.py`, `skill_conditions.py`, `skill_executor.py`, `skill_store.py`, `skill_catalog.py`
- `skill_extractor.py` — LLM-based skill extraction
- `skill_validator.py` — Skill validation and simulation
- `predefined_skills.py` — Built-in skill definitions

### Autonomous Behavior
- `autonomous.py` — AutonomousLoop, idle behavior, learning loop
- `planner.py` — Plan generation
- `rules_engine.py` — Rules-based decisions
- `world_state.py` — World state tracker

### Benchmarking and Tech Tree
- `benchmark.py` / `benchmark_runner.py` / `benchmark_*.py`
- `tech_tree.py` / `tech_tree_runner.py` / `tech_tree_*.py`

### Node.js Bot
- `bot/index.js` — Main bot process with hardened action handlers
- `bot/behaviors/autoEat.js` — Auto-eat when food low
- `bot/behaviors/combat.js` — Auto-attack hostiles
- `bot/behaviors/planExecutor.js` — Multi-step plan execution

## Bridge Protocol

Request:  {"id": N, "action": "<name>", "params": {...}}
Response: {"id": N, "status": "success"|"error", "result": <string|dict>}
Event:    {"id": null, "status": "event", "result": {"type": "<kind>", ...}}

### Hardened Command Responses (Phase 4)

- **collect/mine**: On partial failure, throws with .code, .collected, .explored, .reason
- **craft**: On missing materials, throws with .code, .missing (list), .needsTable
- **smelt**: On no furnace, throws with .code='SMELT_NO_FURNACE'
- **status**: Returns dict with position, health, food, inventory, equipment, nearby_entities, deaths

## Public Tool Functions

| Tool | Purpose |
|------|---------|
| mc_goto | Pathfind to coordinates |
| mc_mine | Mine blocks within 10 blocks |
| mc_build | Place a block |
| mc_attack | Attack entity |
| mc_chat | Send chat message |
| mc_status | Full world state query |
| mc_goal | Set autonomous idle goal |
| mc_stop | Emergency stop |
| mc_collect | Find+approach+mine+pickup |
| mc_craft | Craft from inventory |
| mc_smelt | Smelt in furnace |
| mc_recipes | Query crafting recipes |
| mc_survival_iron | Deterministic wood-to-iron-gear run |

## Testing

```
PYTHONPATH=src python -m pytest tests/tools/minecraft/ -q
```
