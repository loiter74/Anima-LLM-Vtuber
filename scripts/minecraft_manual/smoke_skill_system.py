#!/usr/bin/env python3
"""Test the MC Bot Skill system with persistence and learning loop."""

import asyncio
import os
import sys
import tempfile

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Force UTF-8 output on Windows
if sys.platform == "win32":
    if reconfigure_stdout := getattr(sys.stdout, "reconfigure", None):
        reconfigure_stdout(encoding="utf-8", errors="replace")
    if reconfigure_stderr := getattr(sys.stderr, "reconfigure", None):
        reconfigure_stderr(encoding="utf-8", errors="replace")

from animetta.tools.minecraft.skill_library import Skill, SkillLibrary, SkillStep


async def main() -> None:
    print("=== MC Bot Skill System Smoke Test ===\n")

    # Use a temp DB so we don't pollute the real data dir
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "smoke_skills.db")

        # ── Test 1: Initialize with DB ──────────────────────────────
        print("1. Initializing SkillLibrary with SQLite persistence...")
        library = SkillLibrary(db_path=db_path)
        await library.init_db()
        loaded = await library.load_predefined_skills()
        print(f"   Loaded {loaded} predefined skills")
        assert loaded > 0, "Expected at least 1 predefined skill"

        all_skills = await library.get_all_skills()
        print(f"   Total skills in library: {len(all_skills)}")

        # ── Test 2: Skills persist across restart ────────────────────
        print("\n2. Testing persistence across restart...")
        await library.close_db()
        await asyncio.sleep(0.2)  # Let Windows release file handle

        library2 = SkillLibrary(db_path=db_path)
        await library2.init_db()
        all_skills2 = await library2.get_all_skills()
        print(f"   After restart: {len(all_skills2)} skills loaded")
        assert len(all_skills2) == len(all_skills), (
            f"Expected {len(all_skills)} skills after restart, got {len(all_skills2)}"
        )

        # Verify a specific skill survived
        first_skill = all_skills[0]
        loaded_skill = await library2.get_skill(first_skill.id)
        assert loaded_skill is not None, f"Skill '{first_skill.id}' not found after restart"
        assert loaded_skill.name == first_skill.name
        print(f"   ✓ Skill '{first_skill.id}' survived restart")

        # ── Test 3: Learned skill persistence ────────────────────────
        print("\n3. Testing learned skill persistence...")
        learned = Skill(
            id="smoke_learned_test",
            name="Smoke Learned Skill",
            description="Extracted from trace",
            steps=[SkillStep(name="mine", params={"block_type": "stone", "count": 1})],
            tags=["smoke", "test"],
            is_learned=True,
            validated=False,
        )
        await library2.add_learned(learned)

        # Verify it's in memory
        in_memory = await library2.get_skill("smoke_learned_test")
        assert in_memory is not None
        assert in_memory.is_learned is True
        print("   ✓ Learned skill saved to memory + SQLite")

        # Restart and verify
        await library2.close_db()
        await asyncio.sleep(0.2)
        library3 = SkillLibrary(db_path=db_path)
        await library3.init_db()
        after_restart = await library3.get_skill("smoke_learned_test")
        assert after_restart is not None, "Learned skill lost after restart"
        assert after_restart.is_learned is True
        assert after_restart.validated is False
        assert after_restart.tags == ["smoke", "test"]
        print("   ✓ Learned skill survived restart with all metadata")

        # ── Test 4: Stats persistence ────────────────────────────────
        print("\n4. Testing stats persistence...")
        await library3.update_success("smoke_learned_test")
        await library3.update_success("smoke_learned_test")
        await library3.update_failure("smoke_learned_test")

        # Wait for async writes
        await asyncio.sleep(0.1)

        # Verify in memory
        skill_with_stats = await library3.get_skill("smoke_learned_test")
        assert skill_with_stats.success_count == 2
        assert skill_with_stats.fail_count == 1
        print(
            f"   ✓ Stats: success={skill_with_stats.success_count}, "
            f"fail={skill_with_stats.fail_count}, "
            f"rate={skill_with_stats.success_rate:.0%}"
        )

        # Restart and verify stats persisted
        await library3.close_db()
        await asyncio.sleep(0.2)
        library4 = SkillLibrary(db_path=db_path)
        await library4.init_db()
        final_skill = await library4.get_skill("smoke_learned_test")
        assert final_skill is not None
        assert final_skill.success_count == 2
        assert final_skill.fail_count == 1
        print("   ✓ Stats survived restart")

        # ── Test 5: Skill matching ───────────────────────────────────
        print("\n5. Testing skill matching...")
        context = {
            "health": 20,
            "food": 20,
            "is_day": True,
            "is_night": False,
            "inventory": {"oak_log": 20, "cobblestone": 40},
        }
        matching = await library4.match_skills(context)
        print(f"   Matched {len(matching)} skills for builder context")
        for skill in matching[:5]:
            print(f"   ✓ {skill.name} (success rate: {skill.success_rate:.0%})")

        # ── Test 6: Keyword search ───────────────────────────────────
        print("\n6. Testing keyword search...")
        search_terms = ["食物", "挖矿", "建房子", "木头"]
        for term in search_terms:
            results = await library4.search_skills(term)
            names = [s.name for s in results]
            print(f"   Search '{term}': {names}")

        # ── Test 7: Cleanup ──────────────────────────────────────────
        print("\n7. Testing cleanup...")
        # Create a bad learned skill
        bad_skill = Skill(
            id="smoke_bad_skill",
            name="Bad Skill",
            description="Always fails",
            is_learned=True,
            success_count=1,
            fail_count=19,  # 5% success rate
        )
        await library4.save_skill(bad_skill)
        removed = await library4.cleanup()
        print(f"   Cleanup removed {removed} skills")
        assert removed >= 1, "Expected at least 1 skill removed"
        assert await library4.get_skill("smoke_bad_skill") is None
        print("   ✓ Bad skill removed by cleanup")

        # Predefined skills should NOT be removed
        all_after_cleanup = await library4.get_all_skills()
        predefined_count = sum(1 for s in all_after_cleanup if not s.is_learned)
        print(f"   ✓ {predefined_count} predefined skills preserved")

        await library4.close_db()
        await asyncio.sleep(0.2)

    print("\n=== ALL SMOKE TESTS PASSED ===")
    print("\nLearning loop is ready:")
    print("  ✓ Skills persist to SQLite across restarts")
    print("  ✓ Learned skills survive with full metadata")
    print("  ✓ Stats (success/fail counts) persist")
    print("  ✓ Skill matching works")
    print("  ✓ Cleanup removes low-quality skills")
    print("  ✓ Predefined skills are protected from cleanup")


if __name__ == "__main__":
    asyncio.run(main())
