#!/usr/bin/env python3
"""
TechTreeRunner Debug - Run with detailed error logging
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

from animetta.tools.minecraft.bridge import MinecraftBridge
from animetta.tools.minecraft.config import MinecraftBotConfig, MinecraftConfig


async def main() -> None:
    print("=== TechTreeRunner Debug ===\n")

    # Initialize
    config = MinecraftConfig(
        enabled=True, bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot")
    )
    bridge = MinecraftBridge(config)

    # Start bridge
    print("Starting bridge...")
    started = await bridge.start()
    print(f"Bridge started: {started}")

    if not started:
        print("Failed to start bridge")
        return

    # Wait for bot to be ready
    await asyncio.sleep(3)

    # Test basic commands
    print("\nTesting basic commands...")

    # Test status
    status = await bridge.send_command("status", {})
    print(f"Status: {status.get('status')}")

    # Test collect (simple)
    print("\nTesting collect...")
    result = await bridge.send_command(
        "collect", {"block_type": "oak_log", "count": 1}, timeout=30.0
    )
    print(f"Collect result: {result}")

    # Test craft
    print("\nTesting craft...")
    result = await bridge.send_command("craft", {"recipe": "oak_planks", "count": 1}, timeout=30.0)
    print(f"Craft result: {result}")

    # Check if bridge is still running
    print(f"\nBridge running: {bridge._running}")

    # Stop bridge
    print("\nStopping bridge...")
    await bridge.stop()
    print("Bridge stopped")

    print("\n=== Debug Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
