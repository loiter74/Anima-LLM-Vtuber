#!/usr/bin/env python3
"""
TechTreeRunner Simulation Test

Tests the skill system without actually connecting to Minecraft.
Uses a mock bridge to simulate bot behavior.
"""

import asyncio
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


from animetta.tools.minecraft.skill_library import SkillLibrary

from animetta.tools.minecraft.tech_tree import TechTreeRunner, create_default_tech_tree


class MockBridge:
    """Mock bridge that simulates bot behavior"""

    def __init__(self):
        self.commands = []
        self.inventory = {
            "oak_log": 0,
            "oak_planks": 0,
            "stick": 0,
            "crafting_table": 0,
            "wooden_pickaxe": 0,
            "wooden_sword": 0,
            "cobblestone": 0,
            "stone_pickaxe": 0,
            "stone_sword": 0,
            "furnace": 0,
        }
        self.position = {"x": 0, "y": 64, "z": 0}
        self.health = 20
        self.food = 20

    async def send_command(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Simulate bot commands"""
        self.commands.append((action, params))
        params = params or {}

        if action == "status":
            return {
                "status": "success",
                "result": {
                    "position": self.position,
                    "health": self.health,
                    "food": self.food,
                    "inventory": self.inventory,
                },
            }

        elif action == "collect":
            block_type = params.get("block_type", "")
            count = params.get("count", 1)

            # Simulate collecting resources
            if block_type == "oak_log":
                self.inventory["oak_log"] += count
                return {"status": "success", "result": f"Collected {count} oak_log"}
            elif block_type == "stone":
                self.inventory["cobblestone"] += count
                return {"status": "success", "result": f"Collected {count} stone"}

            return {"status": "error", "result": f"Cannot collect {block_type}"}

        elif action == "craft":
            recipe = params.get("recipe", "")
            count = params.get("count", 1)

            # Simulate crafting
            craftable: dict[str, dict[str, Any]] = {
                "oak_planks": {"requires": {"oak_log": 1}, "produces": 4},
                "stick": {"requires": {"oak_planks": 2}, "produces": 4},
                "crafting_table": {"requires": {"oak_planks": 4}, "produces": 1},
                "wooden_pickaxe": {"requires": {"oak_planks": 3, "stick": 2}, "produces": 1},
                "wooden_sword": {"requires": {"oak_planks": 2, "stick": 1}, "produces": 1},
                "stone_pickaxe": {"requires": {"cobblestone": 3, "stick": 2}, "produces": 1},
                "stone_sword": {"requires": {"cobblestone": 2, "stick": 1}, "produces": 1},
                "furnace": {"requires": {"cobblestone": 8}, "produces": 1},
            }

            if recipe in craftable:
                spec = craftable[recipe]
                # Check materials
                for mat, needed in spec["requires"].items():
                    if self.inventory.get(mat, 0) < needed * count:
                        return {"status": "error", "result": f"Missing {mat}"}

                # Consume materials and produce item
                for mat, needed in spec["requires"].items():
                    self.inventory[mat] -= needed * count

                self.inventory[recipe] = self.inventory.get(recipe, 0) + spec["produces"] * count
                return {"status": "success", "result": f"Crafted {count} {recipe}"}

            return {"status": "error", "result": f"Unknown recipe: {recipe}"}

        elif action == "mine":
            # Same as collect for simplicity
            return await self.send_command("collect", params, timeout)

        return {"status": "error", "result": f"Unknown action: {action}"}


async def main() -> None:
    print("=" * 60)
    print("  TechTreeRunner Simulation Test")
    print("=" * 60)
    print()

    # Create mock bridge
    bridge = MockBridge()
    skill_library = SkillLibrary()

    # Create tech tree config
    config = create_default_tech_tree()
    print(f"Config: {len(config.phases)} phases, {config.total_time_budget_minutes}min total")

    # Create runner
    runner = TechTreeRunner(bridge=bridge, skill_library=skill_library, config=config)

    # Run the tech tree
    print("\nRunning tech tree simulation...")
    metrics = await runner.run()

    # Show results
    print("\n" + "=" * 60)
    print("  Simulation Results")
    print("=" * 60)
    print(f"\nPhases completed: {len(metrics.phases_completed)}/4")
    print(f"Items collected: {metrics.items_collected}")
    print(f"Skills learned: {metrics.skills_learned}")
    print(f"Skills reused: {metrics.skills_reused}")
    print(f"Deaths: {metrics.deaths}")

    if metrics.phases_completed:
        print(f"\nCompleted phases: {', '.join(metrics.phases_completed)}")

    # Show inventory
    print("\nFinal inventory:")
    for item, count in bridge.inventory.items():
        if count > 0:
            print(f"  {item}: {count}")

    # Show commands executed
    print(f"\nCommands executed: {len(bridge.commands)}")
    for i, (action, params) in enumerate(bridge.commands[:20]):  # Show first 20
        print(f"  {i + 1}. {action}({params})")
    if len(bridge.commands) > 20:
        print(f"  ... and {len(bridge.commands) - 20} more")

    # Generate report
    report = runner.generate_report()
    print(f"\nReport generated: {report.timestamp}")
    print(f"Phases completed: {len(report.phase_details)}")

    print("\n" + "=" * 60)
    print("  Simulation Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
