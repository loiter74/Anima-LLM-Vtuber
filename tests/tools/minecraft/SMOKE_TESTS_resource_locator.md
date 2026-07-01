# Resource Locator Smoke Tests

Manual verification checklist for the Resource Locator system.
Run these against a live Minecraft server with the bot connected.

## Prerequisites

- Minecraft server running (Java 1.20.x)
- Bot connected via `PYTHONPATH=src python -m animetta.tools.minecraft.core.socketio_server`
- Bot has basic inventory (empty or starting gear)
- Enable debug logging: set `LOCATOR_DEBUG=1` in bot environment

## Smoke Test 1: Collect oak_log (surface resource)

**Expected behavior:** Uses `surface_sweep` or `spiral_scan` strategy; finds a tree.

```
Action: mc_collect("oak_log", 1)
Success criteria:
  - Bot navigates to nearest oak_log and collects it
  - Response contains "Collected 1 oak_log"
  - Debug log shows: [ResourceLocator] TRY strategy=surface_sweep
  - Debug log shows: [ResourceLocator] FOUND resource=oak_log
```

## Smoke Test 2: Collect sand (shore resource)

**Expected behavior:** Uses `surface_sweep`; finds sand near water.

```
Action: mc_collect("sand", 1)
Success criteria:
  - Bot navigates to sand block and collects it
  - Response contains "Collected 1 sand"
  - Debug log shows strategy selection (memory_first → surface_sweep)
```

## Smoke Test 3: Collect coal_ore (underground resource)

**Expected behavior:** Uses `cave_scan` or `safe_descent`; finds exposed coal vein or descends.

**Prerequisites:** Bot needs at least a wooden pickaxe (craft first if needed).

```
Action: mc_collect("coal_ore", 1)
Success criteria:
  - Bot finds coal_ore (exposed vein or descent)
  - Response contains "Collected 1 coal_ore"
  - Debug log shows strategy chain: memory_first → cave_scan → safe_descent
  - If no wooden pickaxe: error code TOOL_REQUIRED
```

## Smoke Test 4: Collect iron_ore (underground resource)

**Expected behavior:** Uses `cave_scan` or `safe_descent` to find iron.

**Prerequisites:** Bot needs at least a stone pickaxe.

```
Action: mc_collect("iron_ore", 1)
Success criteria:
  - Bot finds iron_ore at appropriate Y-level
  - Response contains "Collected 1 iron_ore"
  - Debug log shows strategies tried
  - If no stone pickaxe: error code TOOL_REQUIRED with requiredTool="stone_pickaxe"
```

## Smoke Test 5: locate_resource diamond_ore (debug/internal)

**Expected behavior:** Attempts deep strategies; likely returns RESOURCE_NOT_FOUND or TOOL_REQUIRED without iron pickaxe.

```
Action (via bridge): locate_resource("diamond_ore")
Success criteria:
  - Returns structured result or structured error
  - If no iron pickaxe: error code TOOL_REQUIRED, requiredTool="iron_pickaxe"
  - If has iron pickaxe: attempts safe_descent → branch_mine
  - Debug log shows full strategy chain attempted
  - Summary endpoint works: locate_resource({debug: true}) returns memory summary
```

## Smoke Test 6: Error recovery — collect with missing tool

**Expected behavior:** Locator returns TOOL_REQUIRED; Python recovery should abort the phase.

```
Setup: Bot has no pickaxe
Action: mc_collect("iron_ore", 1)
Success criteria:
  - Error response contains "TOOL_REQUIRED" or "stone_pickaxe"
  - Recovery system identifies this as abort-worthy
  - Runner does not infinitely retry
```

## Smoke Test 7: Error recovery — unsafe area during descent

**Expected behavior:** Locator encounters lava during safe_descent; returns UNSAFE_AREA.

```
Setup: Bot is above lava level
Action: mc_collect("iron_ore", 1)
  (descent will encounter lava if near Y=-16)
Success criteria:
  - Error response contains "UNSAFE_AREA" or "lava"
  - Recovery system stops and schedules retry
  - Bot does not walk into lava
```

## Debug Endpoint

```python
# Get memory summary (discoveries, depleted, danger, strategy stats)
bridge.send_command("locate_resource", {"debug": True})
# Returns: { discoveries: [...], depleted: N, danger: N, strategyStats: {...} }
```

## Known Limitations (v1)

- Memory is in-process only (resets on bot restart)
- `branch_mine` uses fixed 8-block branch length
- No cross-dimension resource search
- No persistent world map
