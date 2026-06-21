#!/usr/bin/env python3
"""
Simple Bot Test - Test basic operations
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from animetta.tools.minecraft.bridge import MinecraftBridge
from animetta.tools.minecraft.config import MinecraftConfig, MinecraftBotConfig


async def main():
    print("=== Simple Bot Test ===\n")
    
    config = MinecraftConfig(
        enabled=True,
        bot=MinecraftBotConfig(
            host="localhost",
            port=25565,
            username="AnimettaBot"
        )
    )
    bridge = MinecraftBridge(config)
    
    # Start bridge
    print("1. Starting bridge...")
    started = await bridge.start()
    print(f"   Bridge started: {started}")
    
    if not started:
        print("Failed to start bridge")
        return
    
    # Wait for bot to be ready
    await asyncio.sleep(3)
    
    # Test status
    print("\n2. Testing status...")
    status = await bridge.send_command("status", {})
    print(f"   Status: {status.get('status')}")
    if status.get('status') == 'success':
        result = status.get('result', {})
        print(f"   Position: {result.get('position')}")
        print(f"   Health: {result.get('health')}")
        print(f"   Food: {result.get('food')}")
    
    # Test goto
    print("\n3. Testing goto...")
    result = await bridge.send_command("goto", {"x": 10, "y": 64, "z": 10}, timeout=30.0)
    print(f"   Goto result: {result}")
    
    # Test collect with longer timeout
    print("\n4. Testing collect (60s timeout)...")
    result = await bridge.send_command("collect", {"block_type": "oak_log", "count": 1}, timeout=60.0)
    print(f"   Collect result: {result}")
    
    # Test status again
    print("\n5. Testing status again...")
    status = await bridge.send_command("status", {})
    if status.get('status') == 'success':
        result = status.get('result', {})
        inventory = result.get('inventory', {})
        print(f"   Inventory: {inventory}")
    
    # Stop bridge
    print("\n6. Stopping bridge...")
    await bridge.stop()
    print("   Bridge stopped")
    
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
