#!/usr/bin/env python3
"""
Skill Extraction Integration Test

Tests the full flow:
1. Connect to Minecraft server
2. Execute a task (collect wood)
3. Record trace
4. Extract skill from trace
5. Validate and save skill
"""
import asyncio
import json
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from animetta.tools.minecraft.bridge import MinecraftBridge
from animetta.tools.minecraft.trace_recorder import TraceRecorder, ActionTrace
from animetta.tools.minecraft.skill_library import SkillLibrary, Skill, SkillStep
from animetta.tools.minecraft.skill_validator import SkillValidator
from animetta.tools.minecraft.predefined_skills import get_predefined_skills


async def main():
    print("=== Skill Extraction Integration Test ===\n")
    
    # 1. Initialize components
    print("1. Initializing components...")
    # bridge = MinecraftBridge()  # Will be initialized when connecting
    trace_recorder = TraceRecorder()
    skill_library = SkillLibrary()
    skill_validator = SkillValidator()
    
    # Load predefined skills
    for skill in get_predefined_skills():
        await skill_library.save_skill(skill)
    print(f"   Loaded {len(await skill_library.get_all_skills())} predefined skills")
    
    # 2. Connect to Minecraft
    print("\n2. Connecting to Minecraft server...")
    try:
        # For now, simulate the connection
        print("   [SIMULATED] Would connect to localhost:25565")
        print("   [SIMULATED] Username: AnimettaBot")
        print("   [INFO] Full integration requires running bot via bridge.py")
    except Exception as e:
        print(f"   Error: {e}")
        return
    
    # 3. Simulate task execution with trace recording
    print("\n3. Simulating task execution...")
    
    # Start trace
    trace_recorder.start_trace("收集 5 个橡木原木")
    
    # Simulate actions
    actions = [
        {
            "action": "smart_goto",
            "params": {"target": "oak_tree"},
            "result": "success",
            "duration": 5.2,
            "state_before": {"position": {"x": 0, "y": 64, "z": 0}, "health": 20, "food": 18, "inventory": {}},
            "state_after": {"position": {"x": 15, "y": 64, "z": 8}, "health": 20, "food": 18, "inventory": {}}
        },
        {
            "action": "mine",
            "params": {"block_type": "oak_log", "count": 5},
            "result": "success",
            "duration": 12.3,
            "state_before": {"position": {"x": 15, "y": 64, "z": 8}, "health": 20, "food": 17, "inventory": {}},
            "state_after": {"position": {"x": 15, "y": 64, "z": 8}, "health": 20, "food": 16, "inventory": {"oak_log": 5}}
        }
    ]
    
    for action in actions:
        trace_recorder.record_action(
            action=action["action"],
            params=action["params"],
            result=action["result"],
            state_before=action["state_before"],
            state_after=action["state_after"],
            duration=action["duration"]
        )
        print(f"   Recorded: {action['action']}({action['params']}) -> {action['result']}")
    
    # End trace
    trace = trace_recorder.end_trace("success")
    print(f"\n   Trace completed:")
    print(f"     - Goal: {trace.goal}")
    print(f"     - Steps: {len(trace.steps)}")
    print(f"     - Result: {trace.final_result}")
    print(f"     - Duration: {trace.total_duration:.1f}s")
    print(f"     - Items gained: {trace.items_gained}")
    print(f"     - Distance: {trace.distance_traveled:.1f} blocks")
    
    # 4. Extract skill (simulated - would normally call LLM)
    print("\n4. Extracting skill from trace...")
    
    # Create a mock extracted skill
    extracted_skill = Skill(
        id="collect_wood_auto",
        name="自动收集木材",
        description="自动寻找树木并收集木材",
        category="collection",
        preconditions=["has_axe"],
        postconditions=["has_wood"],
        steps=[
            SkillStep(
                name="smart_goto",
                params={"target": "oak_tree"},
                preconditions=[],
                timeout=30.0,
                retry=2
            ),
            SkillStep(
                name="mine",
                params={"block_type": "oak_log", "count": 5},  # int, not str
                preconditions=[],
                timeout=60.0,
                retry=1
            )
        ],
        parameters={"count": "Number of logs to collect"},
        tags=["wood", "logs", "collection", "auto"],
        is_learned=True,
        validated=False
    )
    
    print(f"   Extracted skill: {extracted_skill.name}")
    print(f"   Category: {extracted_skill.category}")
    print(f"   Steps: {len(extracted_skill.steps)}")
    print(f"   Tags: {extracted_skill.tags}")
    
    # 5. Validate skill
    print("\n5. Validating skill...")
    
    validation_result = skill_validator.validate(
        extracted_skill,
        {"health": 20, "food": 16, "inventory": {"oak_log": 5, "oak_axe": 1}}
    )
    
    print(f"   Passed: {validation_result.passed}")
    print(f"   Checks: {validation_result.checks}")
    if validation_result.failures:
        print(f"   Failures: {validation_result.failures}")
    if validation_result.warnings:
        print(f"   Warnings: {validation_result.warnings}")
    
    # 6. Save to library
    if validation_result.passed:
        print("\n6. Saving skill to library...")
        extracted_skill.validated = True
        success = await skill_library.add_learned(extracted_skill)
        print(f"   Saved: {success}")
        
        # Verify it's in the library
        all_skills = await skill_library.get_all_skills()
        learned_skills = await skill_library.get_learned_skills()
        print(f"   Total skills: {len(all_skills)}")
        print(f"   Learned skills: {len(learned_skills)}")
    
    # 7. Save trace to file
    print("\n7. Saving trace to file...")
    await trace_recorder.save_trace(trace)
    print("   Saved to data/mc_traces.jsonl")
    
    # 8. Summary
    print("\n=== Summary ===")
    print(f"Task: {trace.goal}")
    print(f"Result: {trace.final_result}")
    print(f"Skill extracted: {extracted_skill.name}")
    print(f"Skill validated: {validation_result.passed}")
    print(f"Skill saved: {validation_result.passed}")
    print(f"\nNext time a similar task is requested, the bot will:")
    print(f"  1. Search skill library for matching skills")
    print(f"  2. Find '{extracted_skill.name}'")
    print(f"  3. Execute the skill directly (no LLM planning needed)")
    print(f"  4. Track success/failure for continuous improvement")
    
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
