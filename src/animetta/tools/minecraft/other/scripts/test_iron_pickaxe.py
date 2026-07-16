"""Deterministic iron pickaxe crafting script.

Sends exact command sequence to the bot with retries.
Bypasses the general crafting system by using direct commands.

运行：PYTHONPATH=src python -m animetta.tools.minecraft.other.scripts.test_iron_pickaxe
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BOT_DIR = Path(__file__).resolve().parents[2] / "bot"


async def iron_pickaxe() -> None:
    proc = await asyncio.create_subprocess_exec(
        "node",
        "index.js",
        "localhost",
        "25565",
        "IronBot",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(BOT_DIR),
    )

    cmd_id = [0]

    async def send(
        action: str,
        params: dict[str, Any] | None = None,
        timeout: float = 60,
    ) -> dict[str, Any]:
        cmd_id[0] += 1
        command_params = dict(params or {})
        command_params["timeout"] = timeout * 1000
        cmd: dict[str, Any] = {
            "id": cmd_id[0],
            "action": action,
            "params": command_params,
        }
        proc.stdin.write((json.dumps(cmd) + "\n").encode())
        await proc.stdin.drain()
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                if not line:
                    break
                msg = json.loads(line.decode())
                if msg.get("id") == cmd_id[0]:
                    return msg
            except Exception:
                break
        return {"status": "error", "result": "timeout"}

    async def inv() -> dict[str, int]:
        r = await send("status")
        result = r.get("result", {})
        if isinstance(result, dict):
            return result.get("inventory", {})
        return {}

    async def retry(
        action: str,
        params: dict[str, Any],
        need_item: str,
        need_count: int,
        tries: int = 10,
        timeout: float = 90,
        label: str = "",
    ) -> bool:
        for i in range(tries):
            r = await send(action, params, timeout=timeout)
            h = (await inv()).get(need_item, 0)
            if h >= need_count:
                return True
            sys.stdout.write(f"  {label} attempt {i + 1}: {need_item}={h}\n")
            sys.stdout.flush()
            if "busy" in str(r.get("result", "")).lower():
                await asyncio.sleep(3)
        return False

    # Wait for spawn
    for _ in range(30):
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=5)
            msg = json.loads(line.decode())
            if msg.get("result", {}).get("type") == "spawn":
                break
        except Exception:
            pass
    await asyncio.sleep(2)

    # Get position
    r = await send("status")
    pos = r.get("result", {}).get("position", {})
    sys.stdout.write(f"Spawn: {pos}\n")
    sys.stdout.flush()

    # Go to ground level - walk step by step downward
    sys.stdout.write("Descending to ground level...\n")
    sys.stdout.flush()
    r = await send("status")
    pos = r.get("result", {}).get("position", {})
    if isinstance(pos, dict):
        cur_y = int(pos.get("y", 64))
        x, z = int(pos["x"]), int(pos["z"])
        # Walk to lower Y in steps
        while cur_y > 70:
            target_y = max(cur_y - 20, 64)
            sys.stdout.write(f"  Descending from y={cur_y} to y={target_y}...\n")
            sys.stdout.flush()
            await send("goto", {"x": x, "y": target_y, "z": z}, timeout=30)
            r = await send("status")
            result = r.get("result", {})
            if isinstance(result, dict):
                new_y = int(result.get("position", {}).get("y", cur_y))
                if new_y >= cur_y:
                    # Not descending, try walking horizontally
                    sys.stdout.write(f"  Stuck at y={new_y}, walking sideways...\n")
                    sys.stdout.flush()
                    x += 50
                    await send("goto", {"x": x, "y": cur_y, "z": z}, timeout=30)
                    r = await send("status")
                    result = r.get("result", {})
                    if isinstance(result, dict):
                        new_y = int(result.get("position", {}).get("y", cur_y))
                cur_y = new_y
            else:
                break

    r = await send("status")
    pos = r.get("result", {}).get("position", {})
    sys.stdout.write(f"Final position: {pos}\n")
    sys.stdout.flush()

    # === PHASE 1: Collect wood ===
    sys.stdout.write("\n=== PHASE 1: WOOD ===\n")
    sys.stdout.flush()
    ok = await retry(
        "collect",
        {"block_type": "oak_log", "count": 8},
        "oak_log",
        8,
        tries=15,
        timeout=90,
        label="wood",
    )
    i = await inv()
    sys.stdout.write(f"Wood: {'OK' if ok else 'FAIL'} | oak_log={i.get('oak_log', 0)}\n")
    sys.stdout.flush()

    # === PHASE 2: Craft basics ===
    sys.stdout.write("\n=== PHASE 2: CRAFT BASICS ===\n")
    sys.stdout.flush()

    # Craft 4 planks for table
    r = await send("craft", {"recipe": "oak_planks", "count": 4}, timeout=15)
    i = await inv()
    sys.stdout.write(
        f"Planks x4: {r['status']} | planks={i.get('oak_planks', 0)} log={i.get('oak_log', 0)}\n"
    )
    sys.stdout.flush()

    # Check if planks actually exist
    if i.get("oak_planks", 0) < 4:
        sys.stdout.write("ERROR: Not enough planks! Trying again...\n")
        sys.stdout.flush()
        r = await send("craft", {"recipe": "oak_planks", "count": 1}, timeout=15)
        i = await inv()
        sys.stdout.write(f"Planks x1 retry: {r['status']} | planks={i.get('oak_planks', 0)}\n")
        sys.stdout.flush()

    # Craft table
    r = await send("craft", {"recipe": "crafting_table", "count": 1}, timeout=15)
    i = await inv()
    table_count = i.get("crafting_table", 0)
    sys.stdout.write(
        f"Table: {r['status']} | table={table_count} planks={i.get('oak_planks', 0)}\n"
    )
    sys.stdout.flush()

    # If table not in inventory, check what happened
    if table_count == 0:
        sys.stdout.write("WARNING: table=0 after craft. Checking raw inventory...\n")
        sys.stdout.flush()
        r = await send("status")
        raw = r.get("result", {}).get("inventory", {})
        sys.stdout.write(f"Raw inventory: { {k: v for k, v in raw.items() if v > 0} }\n")
        sys.stdout.flush()

        # Try crafting table again
        r = await send("craft", {"recipe": "crafting_table", "count": 1}, timeout=15)
        i = await inv()
        sys.stdout.write(f"Table retry: {r['status']} | table={i.get('crafting_table', 0)}\n")
        sys.stdout.flush()

    # Place table (only if we have one)
    table_pos = None
    if (await inv()).get("crafting_table", 0) > 0:
        r = await send("status")
        pos = r.get("result", {}).get("position", {})
        if isinstance(pos, dict):
            x, y, z = int(pos["x"]), int(pos["y"]), int(pos["z"])
            # Try placing at current Y and below (bot might be floating)
            for dy in range(0, -5, -1):
                for dx, dz in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                    r = await send(
                        "place",
                        {"block_type": "crafting_table", "x": x + dx, "y": y + dy, "z": z + dz},
                    )
                    if r.get("status") == "success":
                        table_pos = {"x": x + dx, "y": y + dy, "z": z + dz}
                        sys.stdout.write(f"Place table: OK at ({x + dx}, {y + dy}, {z + dz})\n")
                        sys.stdout.flush()
                        break
                if table_pos:
                    break
            if not table_pos:
                sys.stdout.write("Place table: FAILED\n")
                sys.stdout.flush()
    else:
        sys.stdout.write("SKIP: No crafting_table to place\n")
        sys.stdout.flush()

    # Craft more planks for sticks + pickaxe
    r = await send("craft", {"recipe": "oak_planks", "count": 2}, timeout=15)
    i = await inv()
    sys.stdout.write(f"Planks x2: {r['status']} | planks={i.get('oak_planks', 0)}\n")
    sys.stdout.flush()

    # Craft sticks
    r = await send("craft", {"recipe": "stick", "count": 4}, timeout=15)
    i = await inv()
    sys.stdout.write(f"Sticks: {r['status']} | sticks={i.get('stick', 0)}\n")
    sys.stdout.flush()

    # Craft more planks for wooden pickaxe (needs 3 planks)
    r = await send("craft", {"recipe": "oak_planks", "count": 3}, timeout=15)
    i = await inv()
    sys.stdout.write(f"Planks x3: {r['status']} | planks={i.get('oak_planks', 0)}\n")
    sys.stdout.flush()

    # Craft wooden pickaxe (navigate to table first)
    if table_pos:
        await send(
            "goto", {"x": table_pos["x"], "y": table_pos["y"], "z": table_pos["z"]}, timeout=15
        )
    r = await send("craft", {"recipe": "wooden_pickaxe", "count": 1}, timeout=20)
    i = await inv()
    sys.stdout.write(f"Wood pickaxe: {r['status']} | wp={i.get('wooden_pickaxe', 0)}\n")
    sys.stdout.flush()

    if not i.get("wooden_pickaxe"):
        sys.stdout.write("Wood pickaxe failed, retrying with new table...\n")
        sys.stdout.flush()
        await send("craft", {"recipe": "oak_planks", "count": 1}, timeout=15)
        await send("craft", {"recipe": "crafting_table", "count": 1}, timeout=15)
        r = await send("status")
        pos = r.get("result", {}).get("position", {})
        if isinstance(pos, dict):
            x, y, z = int(pos["x"]), int(pos["y"]), int(pos["z"])
            for dy in range(0, -5, -1):
                for dx, dz in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                    r = await send(
                        "place",
                        {"block_type": "crafting_table", "x": x + dx, "y": y + dy, "z": z + dz},
                    )
                    if r.get("status") == "success":
                        table_pos = {"x": x + dx, "y": y + dy, "z": z + dz}
                        break
                if table_pos:
                    break
        r = await send("craft", {"recipe": "wooden_pickaxe", "count": 1}, timeout=20)
        i = await inv()
        sys.stdout.write(f"Wood pickaxe retry: {r['status']} | wp={i.get('wooden_pickaxe', 0)}\n")
        sys.stdout.flush()

    # === PHASE 3: Mine stone ===
    sys.stdout.write("\n=== PHASE 3: STONE ===\n")
    sys.stdout.flush()
    ok = await retry(
        "collect",
        {"block_type": "stone", "count": 6},
        "cobblestone",
        3,
        tries=15,
        timeout=90,
        label="stone",
    )
    i = await inv()
    sys.stdout.write(f"Stone: {'OK' if ok else 'FAIL'} | cobble={i.get('cobblestone', 0)}\n")
    sys.stdout.flush()

    # === PHASE 4: Craft stone pickaxe ===
    sys.stdout.write("\n=== PHASE 4: STONE PICKAXE ===\n")
    sys.stdout.flush()
    r = await send("status")
    pos = r.get("result", {}).get("position", {})
    if isinstance(pos, dict):
        x, y, z = int(pos["x"]), int(pos["y"]), int(pos["z"])
        for dy in range(0, -5, -1):
            for dx, dz in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                r = await send(
                    "place", {"block_type": "crafting_table", "x": x + dx, "y": y + dy, "z": z + dz}
                )
                if r.get("status") == "success":
                    break
            else:
                continue
            break
    await send("craft", {"recipe": "stick", "count": 4}, timeout=15)
    r = await send("craft", {"recipe": "stone_pickaxe", "count": 1}, timeout=20)
    i = await inv()
    sys.stdout.write(f"Stone pickaxe: {r['status']} | sp={i.get('stone_pickaxe', 0)}\n")
    sys.stdout.flush()

    # === PHASE 5: Mine coal ===
    sys.stdout.write("\n=== PHASE 5: COAL ===\n")
    sys.stdout.flush()
    ok = await retry(
        "collect",
        {"block_type": "coal_ore", "count": 3},
        "coal",
        1,
        tries=15,
        timeout=90,
        label="coal",
    )
    i = await inv()
    sys.stdout.write(f"Coal: {'OK' if ok else 'FAIL'} | coal={i.get('coal', 0)}\n")
    sys.stdout.flush()

    # === PHASE 6: Mine iron ===
    sys.stdout.write("\n=== PHASE 6: IRON ORE ===\n")
    sys.stdout.flush()
    ok = await retry(
        "collect",
        {"block_type": "iron_ore", "count": 3},
        "raw_iron",
        1,
        tries=15,
        timeout=120,
        label="iron",
    )
    i = await inv()
    sys.stdout.write(f"Iron: {'OK' if ok else 'FAIL'} | raw_iron={i.get('raw_iron', 0)}\n")
    sys.stdout.flush()

    # === PHASE 7: Smelt ===
    sys.stdout.write("\n=== PHASE 7: SMELT ===\n")
    sys.stdout.flush()
    r = await send("smelt", {"item": "raw_iron", "fuel": "coal", "count": 3}, timeout=30)
    sys.stdout.write(f"Smelt: {r['status']}\n")
    sys.stdout.flush()
    sys.stdout.write("Waiting 25s for smelting...\n")
    sys.stdout.flush()
    await asyncio.sleep(25)
    i = await inv()
    sys.stdout.write(f"After smelt: iron_ingot={i.get('iron_ingot', 0)}\n")
    sys.stdout.flush()

    # === PHASE 8: Craft iron pickaxe ===
    sys.stdout.write("\n=== PHASE 8: IRON PICKAXE ===\n")
    sys.stdout.flush()
    r = await send("status")
    pos = r.get("result", {}).get("position", {})
    if isinstance(pos, dict):
        x, y, z = int(pos["x"]), int(pos["y"]), int(pos["z"])
        for dy in range(0, -5, -1):
            for dx, dz in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]:
                r = await send(
                    "place", {"block_type": "crafting_table", "x": x + dx, "y": y + dy, "z": z + dz}
                )
                if r.get("status") == "success":
                    break
            else:
                continue
            break
    await send("craft", {"recipe": "stick", "count": 4}, timeout=15)
    r = await send("craft", {"recipe": "iron_pickaxe", "count": 1}, timeout=20)
    i = await inv()
    ip = i.get("iron_pickaxe", 0)
    sys.stdout.write(f"Iron pickaxe: {r['status']} | ip={ip}\n")
    sys.stdout.flush()

    if ip > 0:
        sys.stdout.write("\n*** IRON PICKAXE CRAFTED! ***\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(f"\nFinal inventory: { {k: v for k, v in i.items() if v > 0} }\n")
        sys.stdout.flush()

    proc.terminate()


if __name__ == "__main__":
    asyncio.run(iron_pickaxe())
