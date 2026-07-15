"""Real-server smoke test for the iron survival runner.

Usage:
    PYTHONPATH=src python -m animetta.tools.minecraft.other.smoke_test --host <server> --port <port> [--username <name>]

Requires a running Minecraft server. The bot will join, progress through
the survival phases, and report results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


async def run_smoke_test(host: str, port: int, username: str) -> dict:
    """Run the full iron survival smoke test against a real server."""
    from animetta.tools.minecraft.core.bridge import MinecraftBridge
    from animetta.tools.minecraft.core.config import MinecraftBotConfig, MinecraftConfig
    from animetta.tools.minecraft.survival.runner import SurvivalIronRunner

    # Create config — use 1.21.4 to match the Paper server
    config = MinecraftConfig(
        bot=MinecraftBotConfig(host=host, port=port, username=username, version="1.21.4"),
    )

    # Start bridge
    bridge = MinecraftBridge(config)
    logger.info(f"Starting bridge to {host}:{port}...")

    if not await bridge.start():
        logger.error("Failed to start bridge")
        return {"success": False, "error": "bridge_start_failed"}

    logger.info("Bridge started, waiting for bot to connect...")

    # Wait for bot to be ready (with timeout)
    try:
        await asyncio.wait_for(bridge._bot_ready.wait(), timeout=30.0)
    except TimeoutError:
        logger.error("Bot did not become ready within 30 seconds")
        await bridge.stop()
        return {"success": False, "error": "bot_ready_timeout"}

    logger.info("Bot connected and ready")

    # Run survival runner
    runner = SurvivalIronRunner(bridge, max_global_timeout=45 * 60)

    logger.info("Starting iron survival run...")
    start_time = time.time()

    try:
        report = await runner.run()
    except Exception as e:
        logger.error(f"Runner exception: {e}")
        await bridge.stop()
        return {"success": False, "error": str(e)}

    elapsed = time.time() - start_time
    logger.info(f"Run completed in {elapsed:.1f}s")

    # Stop bridge
    await bridge.stop()

    # Build result
    result: dict[str, Any] = {
        "success": report.completed,
        "elapsed_seconds": round(elapsed, 1),
        "deaths": report.deaths,
        "final_inventory": report.final_inventory,
        "phase_summary": [],
        "failed_phase": None,
        "failure_reason": None,
    }

    for pr in report.phase_results:
        phase_info = {
            "phase": pr.phase.value,
            "success": pr.success,
            "actions_attempted": pr.actions_attempted,
            "actions_succeeded": pr.actions_succeeded,
        }
        if not pr.success:
            phase_info["failure_category"] = (
                pr.failure_category.value if pr.failure_category else None
            )
            phase_info["failure_message"] = pr.failure_message
            result["failed_phase"] = pr.phase.value
            result["failure_reason"] = pr.failure_message
        result["phase_summary"].append(phase_info)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Iron survival smoke test")
    parser.add_argument("--host", required=True, help="Minecraft server host")
    parser.add_argument("--port", type=int, default=25565, help="Minecraft server port")
    parser.add_argument("--username", default="IronBot", help="Bot username")
    args = parser.parse_args()

    result = asyncio.run(run_smoke_test(args.host, args.port, args.username))

    # Print summary
    print("\n" + "=" * 60)
    print("SMOKE TEST RESULT")
    print("=" * 60)
    print(f"Success: {result['success']}")
    print(f"Elapsed: {result.get('elapsed_seconds', 0)}s")
    print(f"Deaths: {result.get('deaths', 0)}")

    if result.get("failed_phase"):
        print(f"Failed at: {result['failed_phase']}")
        print(f"Reason: {result.get('failure_reason', 'unknown')}")
    elif result.get("error"):
        print(f"Error: {result['error']}")
    else:
        print("All phases completed")

    if result.get("final_inventory"):
        print("\nFinal inventory:")
        for item, count in result["final_inventory"].items():
            if count > 0:
                print(f"  {item}: {count}")

    if result.get("phase_summary"):
        print("\nPhase details:")
        for phase in result["phase_summary"]:
            status = "+" if phase["success"] else "x"
            print(
                f"  {status} {phase['phase']}: {phase['actions_succeeded']}/{phase['actions_attempted']} actions"
            )

    print("=" * 60)

    # Save full result to JSON
    output_path = Path("smoke_test_result.json")
    output_path.write_text(json.dumps(result, indent=2))
    print(f"\nFull result saved to: {output_path}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
