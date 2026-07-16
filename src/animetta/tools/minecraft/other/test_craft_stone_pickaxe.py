"""Stone pickaxe test using RCON to give materials."""

import asyncio
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
os.environ.setdefault("PYTHONPATH", "src")

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import MinecraftBotConfig, MinecraftConfig


def rcon_cmd(cmd: str) -> str:
    """Execute RCON command via docker exec."""
    result = subprocess.run(
        ["docker", "exec", "animetta-mc", "bash", "-c", f"rcon-cli '{cmd}'"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


BOT_USERNAME = "AnimaBot"


async def main() -> bool:
    config = MinecraftConfig(
        bot=MinecraftBotConfig(
            host="localhost",
            port=25565,
            username=BOT_USERNAME,
            version="1.21.4",
        )
    )

    bridge = MinecraftBridge(config)
    print("[TEST] Starting bridge...")
    if not await bridge.start():
        print("[FAIL] Bridge failed to start")
        return False

    try:
        await asyncio.wait_for(bridge._bot_ready.wait(), timeout=30.0)
    except TimeoutError:
        print("[FAIL] Bot connect timeout")
        await bridge.stop()
        return False

    print("[OK] Bot connected")

    # Give materials via RCON while bot is online
    print("[STEP] Giving materials via RCON...")
    r = rcon_cmd(f"give {BOT_USERNAME} minecraft:oak_planks 4")
    print(f"  give planks: {r}")
    r = rcon_cmd(f"give {BOT_USERNAME} minecraft:cobblestone 3")
    print(f"  give cobblestone: {r}")
    r = rcon_cmd(f"give {BOT_USERNAME} minecraft:stick 2")
    print(f"  give sticks: {r}")
    r = rcon_cmd(f"give {BOT_USERNAME} minecraft:crafting_table 1")
    print(f"  give crafting_table: {r}")
    await asyncio.sleep(2)

    # Check inventory
    s = await bridge.send_command("status", timeout=10)
    inv = s.get("result", {}).get("inventory", {}) if s else {}
    print(f"[INV] {json.dumps(inv)}")

    # Place crafting table
    print("[STEP] Placing crafting table...")
    r = await bridge.send_command("place", {"block_type": "crafting_table"}, timeout=30)
    print(f"  Result: {r}")

    # Craft stone pickaxe
    print("[STEP] Crafting stone pickaxe...")
    r = await bridge.send_command("craft", {"recipe": "stone_pickaxe", "count": 1}, timeout=30)
    print(f"[RESULT] {r}")

    # Final check
    s = await bridge.send_command("status", timeout=10)
    inv = s.get("result", {}).get("inventory", {}) if s else {}
    print(f"[FINAL INV] {json.dumps(inv)}")

    if inv.get("stone_pickaxe", 0) > 0:
        print("\n[PASS] Stone pickaxe crafted!")
        await bridge.stop()
        return True

    print("\n[FAIL] No stone pickaxe")
    await bridge.stop()
    return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
