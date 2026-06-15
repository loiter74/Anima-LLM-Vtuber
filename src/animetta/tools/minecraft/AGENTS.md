# MINECRAFT — CROSS-LANGUAGE NODE.JS BOT

**Generated:** 2026-06-15
**Commit:** 10735c3

> Parent: [../AGENTS.md](../AGENTS.md) — tools-wide conventions.

## OVERVIEW

⚠️ **Cross-language hybrid.** A Mineflayer (Node.js) bot embedded inside the Python `tools/` tree. Python parent spawns a Node child process and talks to it via newline-delimited JSON over stdin/stdout. The LLM can autonomously control a Minecraft character through five exposed tools (`mc_goto`, `mc_mine`, `mc_build`, `mc_attack`, `mc_chat`), plus an `AutonomousLoop` drives self-directed behavior when no LLM instruction is active.

## WHERE TO LOOK

| Task | Location | Language | Notes |
|------|----------|----------|-------|
| Add LLM tool wrapper | `tools.py` | Python | `@tool` decorator, register in `config/tools.yaml` |
| New bot behavior | `bot/behaviors/*.js` | **JS** | Mineflayer API — keep action name in sync with bridge |
| Change IPC contract | `bridge.py` + `bot/index.js` | **Both** | Edit both sides or protocol breaks |
| Tweak autonomous logic | `autonomous.py` | Python | `_evaluate()` priority chain |
| Edit personality/rules | `rules.md` | YAML | Requires Anima restart (no hot reload) |
| Add safety check | `rules_engine.py` | Python | `validate()` runs at startup |
| Parse bot state | `world_state.py` | Python | `WorldState.from_status(resp)` |

## IPC PROTOCOL (the non-obvious thing)

Spawned via `asyncio.create_subprocess_exec("node", "bot/index.js", host, port, username)` with `cwd=bot/`. Requires `bot/node_modules` (run `npm install` in `bot/`).

**Wire format — one JSON object per line, UTF-8, `\n`-terminated:**

```
Python (bridge.py)                         Node.js (bot/index.js)
  │
  │  ── stdin ──────────────────────────────►
  │  {"id": 1, "action": "goto", "params": {"x":100,"y":64,"z":200}}
  │                                          ├── parse, dispatch to behavior
  │                                          │
  │  ◄────────────────────────── stdout ────  {"id": 1, "status": "success", "result": "Arrived"}
  │
  │  ◄────────────────────────── stdout ────  {"id": null, "status": "event",
  │                                             "result": {"type":"heartbeat", ...}}
```

**Message types:**
- **Request**: `{"id": <int>, "action": <str>, "params": <dict>}` — id correlates response
- **Response**: `{"id": <int>, "status": "success"|"error", "result": <any>}` — matched by id via `_pending` future map
- **Event**: `{"id": null | "system", "status": "event", "result": {"type": ...}}` — unsolicited; known types: `login` (sets `_bot_ready`), `spawn`, `heartbeat`

**Action vocabulary** (case-sensitive, both sides MUST agree):
- Movement: `goto {x,y,z}`, `collect {block_type, count}`
- World: `status {}` → full state snapshot, `place {block_type, x, y, z}`
- Combat: `attack {target: "nearest_hostile"}`
- Social: `chat {message: <str>}`
- Mode switch: `set_mode {mode: "planner"|"rule", plan?: [...]}`, `plan_status {}`

**Invariants:**
- Default command timeout: 60s; login readiness wait: 15s for `login` event
- All pending futures resolve with `{"status":"error","result":"Bridge stopped"}` on shutdown

## rules.md FORMAT

YAML with four top-level sections, parsed by `RulesEngine`:
- `priorities: [survival, maintenance, building, gathering, social, exploration]` — decision ordering (lower index = higher priority)
- `building: {target, blueprint, required_materials, build_plan}` — construction target + steps
- `safety: {auto_heal_threshold, return_to_base_at_night, max_build_height}` — survival thresholds
- `chat: {proactive_chance, cooldown_seconds, topics}` — proactive chat config

`RulesEngine.validate()` runs at construction and warns on impossible configs (e.g. `auto_heal_threshold > 20` → "will never trigger" since max health = 20).

## AUTONOMOUSLOOP

Drives behavior when LLM is idle. Tick interval: random 3–8s. Lifecycle: `start()` → `pause()` (LLM instruction arrives) → `resume()` → `stop()`. Decision priority chain (`_evaluate`, survival always #1):
1. **Threat interrupt** — `threat_level >= 2 && nearest_threat_distance < 15` → `attack` (runs even mid-action via `_threat_check`)
2. **Low health** → auto-heal
3. **Night return** → `goto` base
4. **Building maintenance** → material gaps = `gather`; materials satisfied = `place` next step
5. **Proactive chat** — roll `proactive_chance`, pick trigger
6. **Exploration** — random walk ±10 blocks (fallback)

Cooldown: 30s per action category (gather/build/chat/explore), tracked in `CooldownTracker`.

## CONVENTIONS

- **Node.js is optional at runtime** — `is_service_available("node")` guards startup; if absent, bridge logs "skipped" and other tools still function
- **`bot/node_modules` MUST exist** — bridge refuses to start otherwise; run `npm install` in `bot/` before first run
- **Action names are the contract** — adding a behavior requires edits in both `bot/index.js` (dispatch) and the Python caller
- **Two execution modes**: `rule` (Python `AutonomousLoop` drives) vs `planner` (LLM provides plan_steps, Node executes autonomously) — switch via `set_mode`

## ANTI-PATTERNS

- ❌ Never edit `bot/*.js` from a Python task without also updating the action caller — protocol breaks silently
- ❌ Never assume synchronous responses — `send_command` is async, returns a future
- ❌ Never remove `bot/` thinking it's "just a bot" — Python `__init__.py` imports will break
- ❌ Never bypass `rules_engine.py` survival checks — threat/health gates are #1 priority
- ❌ Never set `auto_heal_threshold > 20` — max health is 20, rule will never fire (validator warns)
- ❌ Never reuse `cmd_id` — `_next_id` is monotonic; collisions corrupt the pending future map

## NOTES

- Module-level singleton: `get_bridge()` returns the global `MinecraftBridge` (or `None` if not started)
- MCP bridge (parent `tools/mcp_bridge.py`) is SEPARATE — Minecraft does NOT go through MCP
- `pause_autonomous()` / `resume_autonomous()` are called by the orchestration layer around LLM tool calls to prevent autonomous/LLM command interleaving
- Bot stderr is logged at DEBUG level under `[MinecraftBot]` prefix — Mineflayer is noisy, do not raise to INFO
- Max 5 Minecraft tool calls per LLM turn (shared limit with all tools); per-call timeout configurable in `config/tools.yaml`
