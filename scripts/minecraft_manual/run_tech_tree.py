#!/usr/bin/env python3
"""
TechTreeRunner Execution Script

Runs the full tech tree unlock sequence on a Minecraft server.
Target: 1 hour autonomous run to unlock wood → stone → iron → diamond
"""

import asyncio
import os
import sys
import time

from loguru import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from animetta.tools.minecraft.bridge import MinecraftBridge
from animetta.tools.minecraft.config import MinecraftBotConfig, MinecraftConfig
from animetta.tools.minecraft.skill_extractor import SkillExtractor
from animetta.tools.minecraft.skill_library import SkillLibrary
from animetta.tools.minecraft.skill_validator import SkillValidator
from animetta.tools.minecraft.trace_recorder import TraceRecorder

from animetta.tools.minecraft.tech_tree import TechTreeRunner, create_default_tech_tree


async def main() -> None:
    print("=" * 60)
    print("  TechTreeRunner - Autonomous Tech Tree Unlock")
    print("=" * 60)
    print()

    # 1. Initialize components
    print("[1/5] Initializing components...")
    config = MinecraftConfig(
        enabled=True, bot=MinecraftBotConfig(host="localhost", port=25565, username="AnimettaBot")
    )
    bridge = MinecraftBridge(config)
    skill_library = SkillLibrary()
    _trace_recorder = TraceRecorder()
    _skill_extractor = SkillExtractor(llm_service=None)  # No LLM for now
    _skill_validator = SkillValidator()

    print("  [OK] Bridge initialized")
    print("  [OK] Skill library initialized")
    print("  [OK] Trace recorder initialized")

    # 2. Create TechTree config
    print("\n[2/5] Creating tech tree config...")
    tech_tree_config = create_default_tech_tree()
    print(
        f"  [OK] {len(tech_tree_config.phases)} phases, {tech_tree_config.total_time_budget_minutes}min total"
    )
    for phase in tech_tree_config.phases:
        print(
            f"    - {phase.name}: {phase.time_budget_minutes}min → {list(phase.required_items.keys())}"
        )

    # 3. Start bridge
    print("\n[3/5] Starting Minecraft bot...")
    try:
        started = await bridge.start()
        if not started:
            print("  [FAIL] Failed to start bridge")
            return
        print("  [OK] Bot started, waiting for login...")
        await asyncio.sleep(3)

        # Get initial status
        status = await bridge.send_command("status", {})
        if status.get("status") == "success":
            result = status.get("result", {})
            pos = result.get("position", {})
            print(
                f"  [OK] Position: ({pos.get('x', 0):.0f}, {pos.get('y', 0):.0f}, {pos.get('z', 0):.0f})"
            )
            print(f"  [OK] Health: {result.get('health', '?')}")
            print(f"  [OK] Food: {result.get('food', '?')}")
        else:
            print(f"  [FAIL] Status failed: {status}")
            return
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return

    # 4. Create TechTreeRunner
    print("\n[4/5] Creating TechTreeRunner...")
    runner = TechTreeRunner(bridge=bridge, skill_library=skill_library, config=tech_tree_config)
    print("  [OK] Runner created")

    # 5. Run!
    print("\n[5/5] Starting tech tree unlock...")
    print("=" * 60)
    print("  Bot will now autonomously unlock the tech tree!")
    print("  Target: 1 hour (60 minutes)")
    print("  Phases: wood → stone → iron → diamond")
    print("=" * 60)
    print()

    start_time = time.time()

    try:
        metrics = await runner.run()

        elapsed = time.time() - start_time

        print("\n" + "=" * 60)
        print("  Tech Tree Unlock Complete!")
        print("=" * 60)
        print(f"\n  Result: {'SUCCESS' if len(metrics.phases_completed) == 4 else 'PARTIAL'}")
        print(f"  Time: {elapsed / 60:.1f} minutes")
        print(f"  Phases completed: {len(metrics.phases_completed)}/4")
        print(f"  Items collected: {len(metrics.items_collected)}")
        print(f"  Skills learned: {metrics.skills_learned}")
        print(f"  Skills reused: {metrics.skills_reused}")
        print(f"  Deaths: {metrics.deaths}")

        if metrics.phases_completed:
            print(f"\n  Completed phases: {', '.join(metrics.phases_completed)}")

        # Generate report
        report = runner.generate_report()
        report_path = runner.save_report(report)
        print(f"\n  Report saved: {report_path}")

    except KeyboardInterrupt:
        print("\n\n  Interrupted by user")
    except Exception as e:
        print(f"\n\n  Error: {e}")
        logger.exception("Tech tree unlock failed")
    finally:
        print("\n  Stopping bot...")
        await bridge.stop()
        print("  [OK] Bot stopped")

    print("\n" + "=" * 60)
    print("  Done!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
