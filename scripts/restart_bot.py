#!/usr/bin/env python3
"""Restart MC bot with survival hardening + bootstrap tools + diamond goal."""

import asyncio
import sys

sys.path.insert(0, "src")
sys.stdout.reconfigure(line_buffering=True)


async def main():
    from animetta.tools.minecraft.core.bridge import MinecraftBridge, get_bridge
    from animetta.tools.minecraft.core.config import MinecraftConfig

    # Stop existing
    bridge = get_bridge()
    if bridge and bridge.is_running:
        print("[restart] Stopping...", flush=True)
        await bridge.stop()

    # Start fresh
    config = MinecraftConfig(enabled=True, autonomous=True)
    new_bridge = MinecraftBridge(config, autonomous=True)
    print("[restart] Starting bot...", flush=True)
    started = await new_bridge.start()
    if not started:
        print("[restart] FAILED", flush=True)
        return
    print(f"[restart] Bot online", flush=True)

    # Bootstrap: craft basic tools
    steps = [
        ("collect oak_log x4", {"block_type": "oak_log", "count": 4}, 90),
        ("craft oak_planks x8", {"recipe": "oak_planks", "count": 8}, 15),
        ("craft stick x4", {"recipe": "stick", "count": 4}, 15),
        ("craft wooden_pickaxe", {"recipe": "wooden_pickaxe", "count": 1}, 15),
    ]
    for label, params, timeout in steps:
        print(f"  [{label}]...", flush=True)
        r = await new_bridge.send_command(
            "craft" if "craft" in label else "collect", params, timeout=timeout
        )
        status = r.get("status", "unknown")
        print(f"    → {status}: {r.get('result', '')}", flush=True)
        if status != "success":
            print(f"    [WARN] Step failed, continuing...", flush=True)

    # Mine stone for stone pickaxe
    print("  [mine stone x3]...", flush=True)
    r = await new_bridge.send_command("mine", {"block_type": "stone", "count": 3}, timeout=60.0)
    print(f"    → {r.get('status')}: {r.get('result', '')}", flush=True)

    print("  [craft stone_pickaxe]...", flush=True)
    r = await new_bridge.send_command(
        "craft", {"recipe": "stone_pickaxe", "count": 1}, timeout=30.0
    )
    print(f"    → {r.get('status')}: {r.get('result', '')}", flush=True)

    # Set goal
    await new_bridge.send_command(
        "setgoal", {"goal": "mine diamonds y<16, survive 2 nights"}, timeout=5.0
    )

    # Status
    s = await new_bridge.send_command("status", timeout=10.0)
    if s.get("status") == "success":
        inv = s["result"].get("inventory", {})
        pos = s["result"].get("position", {})
        tools = {
            k: v
            for k, v in inv.items()
            if any(w in k for w in ["pickaxe", "sword", "axe", "planks", "log"])
        }
        print(
            f"[status] Pos=({pos.get('x', 0):.0f},{pos.get('y', 0):.0f},{pos.get('z', 0):.0f}) HP={s['result']['health']} Food={s['result']['food']}",
            flush=True,
        )
        print(f"[status] Tools: {tools}", flush=True)

    print("[restart] Bootstrap done. Autonomous loop active.", flush=True)
    print(
        "[restart] Survival rules: weapon recovery | combat eating | health flee | pickaxe equip | lava escape",
        flush=True,
    )
    print("[restart] Goal: mine diamonds + survive 2 nights", flush=True)
    print("[restart] Monitoring (every 15s)...", flush=True)

    # Monitor
    try:
        while new_bridge.is_running:
            await asyncio.sleep(15)
            st = await new_bridge.send_command("status", timeout=5.0)
            if st.get("status") == "success":
                s = st["result"]
                pos = s.get("position", {})
                inv = s.get("inventory", {})
                dia = inv.get("diamond", 0)
                iron = inv.get("iron_ingot", 0)
                pick = (
                    "iron"
                    if inv.get("iron_pickaxe", 0) > 0
                    else "stone"
                    if inv.get("stone_pickaxe", 0) > 0
                    else "wood"
                    if inv.get("wooden_pickaxe", 0) > 0
                    else "none"
                )
                print(
                    f"  [{pos.get('x', 0):.0f},{pos.get('y', 0):.0f},{pos.get('z', 0):.0f}] HP={s.get('health')} Food={s.get('food')} Dia={dia} Fe={iron} Pick={pick}",
                    flush=True,
                )
    except KeyboardInterrupt:
        print("[restart] Stopping...", flush=True)
        await new_bridge.stop()


asyncio.run(main())
