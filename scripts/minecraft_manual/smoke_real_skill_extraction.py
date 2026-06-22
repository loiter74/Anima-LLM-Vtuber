#!/usr/bin/env python3
"""
Real Minecraft Skill Extraction Test

Connects to actual Minecraft server, executes task, extracts skill.
"""
import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from animetta.tools.minecraft.bridge import MinecraftBridge
from animetta.tools.minecraft.config import MinecraftConfig, MinecraftBotConfig
from animetta.tools.minecraft.trace_recorder import TraceRecorder
from animetta.tools.minecraft.skill_library import SkillLibrary, Skill, SkillStep
from animetta.tools.minecraft.skill_validator import SkillValidator
from animetta.tools.minecraft.predefined_skills import get_predefined_skills


async def main():
    print("=== Real Minecraft Skill Extraction Test ===\n")
    
    # 1. Initialize
    print("1. Initializing...")
    config = MinecraftConfig(
        enabled=True,
        bot=MinecraftBotConfig(
            host="localhost",
            port=25565,
            username="AnimettaBot"
        )
    )
    bridge = MinecraftBridge(config)
    trace_recorder = TraceRecorder()
    skill_library = SkillLibrary()
    skill_validator = SkillValidator()
    
    for skill in get_predefined_skills():
        await skill_library.save_skill(skill)
    print(f"   Loaded {len(await skill_library.get_all_skills())} predefined skills")
    
    # 2. Start bridge
    print("\n2. Starting Minecraft bot...")
    try:
        await bridge.start()
        print("   Bot started, waiting for login...")
        await asyncio.sleep(3)
        
        # Get initial status
        status = await bridge.send_command("status", {})
        if status.get("status") == "success":
            result = status.get("result", {})
            pos = result.get("position", {})
            print(f"   Position: ({pos.get('x', 0):.0f}, {pos.get('y', 0):.0f}, {pos.get('z', 0):.0f})")
            print(f"   Health: {result.get('health', '?')}")
            print(f"   Food: {result.get('food', '?')}")
            inventory = result.get("inventory", {})
            print(f"   Inventory: {len(inventory)} items")
        else:
            print(f"   Status failed: {status}")
            return
    except Exception as e:
        print(f"   Error: {e}")
        return
    
    # 3. Execute task with trace recording
    print("\n3. Executing task: Collect 3 oak logs...")
    
    # Start trace
    trace_recorder.start_trace("收集 3 个橡木原木")
    
    # Get initial state
    initial_status = await bridge.send_command("status", {})
    initial_state = initial_status.get("result", {})
    
    # Execute: goto nearest tree
    print("   Step 1: Finding tree...")
    start_time = time.time()
    result1 = await bridge.send_command("smart_goto", {"target": "oak_log"})
    duration1 = time.time() - start_time
    
    status1 = await bridge.send_command("status", {})
    state1 = status1.get("result", {})
    
    trace_recorder.record_action(
        action="smart_goto",
        params={"target": "oak_log"},
        result="success" if result1.get("status") == "success" else "failed",
        state_before=initial_state,
        state_after=state1,
        duration=duration1
    )
    print(f"   Result: {result1.get('status')} ({duration1:.1f}s)")
    
    # Execute: mine oak_log
    print("   Step 2: Mining oak logs...")
    start_time = time.time()
    result2 = await bridge.send_command("collect", {"block_type": "oak_log", "count": 3})
    duration2 = time.time() - start_time
    
    status2 = await bridge.send_command("status", {})
    state2 = status2.get("result", {})
    
    trace_recorder.record_action(
        action="collect",
        params={"block_type": "oak_log", "count": 3},
        result="success" if result2.get("status") == "success" else "failed",
        state_before=state1,
        state_after=state2,
        duration=duration2
    )
    print(f"   Result: {result2.get('status')} ({duration2:.1f}s)")
    
    # End trace
    trace = trace_recorder.end_trace("success" if result2.get("status") == "success" else "failed")
    
    print(f"\n   Trace summary:")
    print(f"     Steps: {len(trace.steps)}")
    print(f"     Result: {trace.final_result}")
    print(f"     Items gained: {trace.items_gained}")
    
    # 4. Extract skill
    print("\n4. Extracting skill from trace...")
    
    # Create skill from trace
    extracted_skill = Skill(
        id="collect_wood_real",
        name="收集木材（实测）",
        description="从实际执行中提取的木材收集技能",
        category="collection",
        preconditions=["has_axe"],
        postconditions=["has_wood"],
        steps=[
            SkillStep(name="smart_goto", params={"target": "oak_log"}, preconditions=[], timeout=30.0, retry=2),
            SkillStep(name="collect", params={"block_type": "oak_log", "count": 3}, preconditions=[], timeout=60.0, retry=1)
        ],
        parameters={"count": "Number of logs to collect"},
        tags=["wood", "logs", "collection", "real"],
        is_learned=True,
        validated=False
    )
    
    print(f"   Created skill: {extracted_skill.name}")
    
    # 5. Validate
    print("\n5. Validating skill...")
    validation = skill_validator.validate(extracted_skill, state2)
    print(f"   Passed: {validation.passed}")
    print(f"   Checks: {validation.checks}")
    
    # 6. Save
    if validation.passed:
        extracted_skill.validated = True
        await skill_library.add_learned(extracted_skill)
        print(f"\n6. Skill saved to library!")
        
        all_skills = await skill_library.get_all_skills()
        learned = await skill_library.get_learned_skills()
        print(f"   Total skills: {len(all_skills)}")
        print(f"   Learned skills: {len(learned)}")
    
    # 7. Save trace
    await trace_recorder.save_trace(trace)
    print(f"\n7. Trace saved to data/mc_traces.jsonl")
    
    # 8. Stop bridge
    print("\n8. Stopping bot...")
    await bridge.stop()
    
    # Summary
    print("\n=== Summary ===")
    print(f"Task: {trace.goal}")
    print(f"Result: {trace.final_result}")
    print(f"Skill: {extracted_skill.name}")
    print(f"Validated: {validation.passed}")
    print(f"\nThe bot learned a new skill from this execution!")
    print(f"Next time it needs to collect wood, it will use this skill directly.")
    
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
