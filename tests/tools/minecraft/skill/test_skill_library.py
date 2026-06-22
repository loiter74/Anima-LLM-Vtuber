"""
Tests for Skill Library
"""


import pytest

from animetta.tools.minecraft.skill.library import (
    Skill,
    SkillLibrary,
    SkillStep,
    _check_single,
    check_preconditions,
)


@pytest.fixture
def skill_library():
    return SkillLibrary()


@pytest.fixture
def sample_skill():
    return Skill(
        id="mine_oak",
        name="Mine Oak",
        description="Mine oak logs from trees",
        parameters={"count": "int"},
        preconditions=["has_tool('axe')"],
        body={"type": "plan", "steps": [{"action": "mine", "params": {"block_type": "oak_log"}}]},
        postconditions=["inventory_gte('oak_log', count)"],
        tags=["mining", "wood", "resources"]
    )


class TestSkill:
    """Test Skill data class"""

    def test_skill_creation(self, sample_skill):
        """Skill can be created with all fields"""
        assert sample_skill.id == "mine_oak"
        assert sample_skill.name == "Mine Oak"
        assert sample_skill.success_rate == 0.0

    def test_skill_success_rate(self):
        """Success rate calculation is correct"""
        skill = Skill(
            id="test",
            name="Test",
            description="Test skill",
            success_count=7,
            fail_count=3
        )
        assert skill.success_rate == 0.7

    def test_skill_success_rate_zero(self):
        """Success rate is 0 when no attempts"""
        skill = Skill(id="test", name="Test", description="Test")
        assert skill.success_rate == 0.0

    def test_skill_serialization(self, sample_skill):
        """Skill can be serialized to dict and back"""
        data = sample_skill.to_dict()
        restored = Skill.from_dict(data)
        assert restored.id == sample_skill.id
        assert restored.name == sample_skill.name


class TestSkillLibrary:
    """Test SkillLibrary operations"""

    async def test_save_and_retrieve(self, skill_library, sample_skill):
        """Save skill and retrieve by ID"""
        await skill_library.save_skill(sample_skill)
        retrieved = await skill_library.get_skill("mine_oak")
        assert retrieved is not None
        assert retrieved.id == "mine_oak"

    async def test_search_skills(self, skill_library, sample_skill):
        """Search skills by description"""
        await skill_library.save_skill(sample_skill)
        results = await skill_library.search_skills("mine wood")
        assert len(results) > 0
        assert results[0].id == "mine_oak"

    async def test_search_skills_no_match(self, skill_library):
        """Search returns empty for no match"""
        results = await skill_library.search_skills("nonexistent")
        assert results == []

    async def test_search_by_tags(self, skill_library, sample_skill):
        """Search skills by tags"""
        await skill_library.save_skill(sample_skill)
        results = await skill_library.search_by_tags(["mining"])
        assert len(results) > 0

    async def test_update_success(self, skill_library, sample_skill):
        """Update skill success count"""
        await skill_library.save_skill(sample_skill)
        await skill_library.update_success("mine_oak")
        skill = await skill_library.get_skill("mine_oak")
        assert skill.success_count == 1
        assert skill.last_used != ""

    async def test_update_failure(self, skill_library, sample_skill):
        """Update skill failure count"""
        await skill_library.save_skill(sample_skill)
        await skill_library.update_failure("mine_oak")
        skill = await skill_library.get_skill("mine_oak")
        assert skill.fail_count == 1

    async def test_remove_skill(self, skill_library, sample_skill):
        """Remove skill from library"""
        await skill_library.save_skill(sample_skill)
        await skill_library.remove_skill("mine_oak")
        retrieved = await skill_library.get_skill("mine_oak")
        assert retrieved is None

    async def test_cleanup_low_quality(self, skill_library):
        """Cleanup removes low-quality skills"""
        # Create a skill with low success rate and enough attempts.
        # cleanup() only removes learned skills, so mark is_learned=True.
        skill = Skill(
            id="bad_skill",
            name="Bad Skill",
            description="This skill fails a lot",
            success_count=2,
            fail_count=8,
            is_learned=True,
        )
        await skill_library.save_skill(skill)
        # Need at least 10 total attempts for cleanup
        assert skill.success_rate < 0.3
        assert skill.success_count + skill.fail_count >= 10
        await skill_library.cleanup()
        retrieved = await skill_library.get_skill("bad_skill")
        assert retrieved is None

    async def test_get_all_skills(self, skill_library, sample_skill):
        """Get all skills"""
        await skill_library.save_skill(sample_skill)
        all_skills = await skill_library.get_all_skills()
        assert len(all_skills) == 1


# ── Condition Parsing Tests ────────────────────────────────────────────────────


class TestCheckSingleHasPrefix:
    """_check_single with has_X patterns."""

    def test_has_X_boolean_false(self) -> None:
        """has_pickaxe returns False when inventory has none."""
        ctx = {"inventory": {}}
        assert _check_single("has_pickaxe", ctx) is False

    def test_has_X_boolean_true(self) -> None:
        """has_oak_log returns True when inventory has > 0."""
        ctx = {"inventory": {"oak_log": 5}}
        assert _check_single("has_oak_log", ctx) is True

    def test_has_X_boolean_zero(self) -> None:
        """has_stone returns False when inventory count is 0."""
        ctx = {"inventory": {"stone": 0}}
        assert _check_single("has_stone", ctx) is False

    def test_has_X_ge_true(self) -> None:
        """has_oak_log >= 3 returns True when sufficient."""
        ctx = {"inventory": {"oak_log": 5}}
        assert _check_single("has_oak_log >= 3", ctx) is True

    def test_has_X_ge_false(self) -> None:
        """has_oak_log >= 10 returns False when insufficient."""
        ctx = {"inventory": {"oak_log": 5}}
        assert _check_single("has_oak_log >= 10", ctx) is False

    def test_has_X_ge_exact(self) -> None:
        """has_cobblestone >= 32 returns True when exactly 32."""
        ctx = {"inventory": {"cobblestone": 32}}
        assert _check_single("has_cobblestone >= 32", ctx) is True

    def test_has_X_le_true(self) -> None:
        """has_food <= 10 returns True when less than limit."""
        ctx = {"inventory": {"food": 3}}
        assert _check_single("has_food <= 10", ctx) is True

    def test_has_X_le_false(self) -> None:
        """has_food <= 10 returns False when exceeds limit."""
        ctx = {"inventory": {"food": 15}}
        assert _check_single("has_food <= 10", ctx) is False

    def test_has_X_gt_true(self) -> None:
        """has_iron_ingot > 10 returns True."""
        ctx = {"inventory": {"iron_ingot": 15}}
        assert _check_single("has_iron_ingot > 10", ctx) is True

    def test_has_X_gt_false(self) -> None:
        """has_iron_ingot > 10 returns False when equal."""
        ctx = {"inventory": {"iron_ingot": 10}}
        assert _check_single("has_iron_ingot > 10", ctx) is False

    def test_has_X_lt_true(self) -> None:
        """has_diamond < 5 returns True when below."""
        ctx = {"inventory": {"diamond": 2}}
        assert _check_single("has_diamond < 5", ctx) is True

    def test_has_X_lt_false(self) -> None:
        """has_diamond < 5 returns False when above."""
        ctx = {"inventory": {"diamond": 10}}
        assert _check_single("has_diamond < 5", ctx) is False

    def test_has_X_eq_true(self) -> None:
        """has_gold_ingot == 3 returns True when exact."""
        ctx = {"inventory": {"gold_ingot": 3}}
        assert _check_single("has_gold_ingot == 3", ctx) is True

    def test_has_X_eq_false(self) -> None:
        """has_gold_ingot == 3 returns False when different."""
        ctx = {"inventory": {"gold_ingot": 1}}
        assert _check_single("has_gold_ingot == 3", ctx) is False

    def test_has_X_ne_false(self) -> None:
        """has_diamond != 0 returns False when 0."""
        ctx = {"inventory": {"diamond": 0}}
        assert _check_single("has_diamond != 0", ctx) is False

    def test_has_X_ne_true(self) -> None:
        """has_diamond != 0 returns True when non-zero."""
        ctx = {"inventory": {"diamond": 5}}
        assert _check_single("has_diamond != 0", ctx) is True

    def test_has_X_missing_inventory(self) -> None:
        """has_stick >= 5 returns False when item not in inventory."""
        ctx = {"inventory": {"oak_log": 3}}
        assert _check_single("has_stick >= 5", ctx) is False

    def test_has_X_inventory_absent(self) -> None:
        """has_oak_log >= 3 returns False when inventory key missing."""
        ctx = {}
        assert _check_single("has_oak_log >= 3", ctx) is False

    def test_has_X_non_numeric_value(self) -> None:
        """has_axe >= 1 with non-numeric inventory returns False."""
        ctx = {"inventory": {"axe": "broken"}}
        assert _check_single("has_axe >= 1", ctx) is False

    def test_has_iron_ingot_underscore_quantity(self) -> None:
        """has_iron_ingot >= 24 works with underscores in item name."""
        ctx = {"inventory": {"iron_ingot": 30}}
        assert _check_single("has_iron_ingot >= 24", ctx) is True


class TestCheckSingleStandard:
    """_check_single with standard key comparisons (no has_ prefix)."""

    def test_food_lt_true(self) -> None:
        """food < 15 returns True when hungry."""
        ctx = {"food": 10}
        assert _check_single("food < 15", ctx) is True

    def test_food_lt_false(self) -> None:
        """food < 15 returns False when full."""
        ctx = {"food": 18}
        assert _check_single("food < 15", ctx) is False

    def test_health_gt_true(self) -> None:
        """health > 6 returns True when healthy."""
        ctx = {"health": 15.0}
        assert _check_single("health > 6", ctx) is True

    def test_health_gt_false(self) -> None:
        """health > 6 returns False when injured."""
        ctx = {"health": 3.0}
        assert _check_single("health > 6", ctx) is False

    def test_health_ge_boundary(self) -> None:
        """health >= 20 returns True when full."""
        ctx = {"health": 20.0}
        assert _check_single("health >= 20", ctx) is True

    def test_health_le_true(self) -> None:
        """health <= 10 returns True when low."""
        ctx = {"health": 5.0}
        assert _check_single("health <= 10", ctx) is True

    def test_missing_key_returns_false(self) -> None:
        """Missing key returns False."""
        ctx = {}
        assert _check_single("food < 15", ctx) is False

    def test_bool_flag_true(self) -> None:
        """is_night returns True when truthy."""
        ctx = {"is_night": True}
        assert _check_single("is_night", ctx) is True

    def test_bool_flag_false(self) -> None:
        """is_night returns False when falsy."""
        ctx = {"is_night": False}
        assert _check_single("is_night", ctx) is False

    def test_bool_flag_missing(self) -> None:
        """Missing boolean flag returns False."""
        ctx = {}
        assert _check_single("is_night", ctx) is False

    def test_eq_string_true(self) -> None:
        """key == value string comparison works."""
        ctx = {"mode": "survival"}
        assert _check_single("mode == survival", ctx) is True

    def test_eq_string_false(self) -> None:
        """key == value string mismatch returns False."""
        ctx = {"mode": "creative"}
        assert _check_single("mode == survival", ctx) is False


class TestCheckPreconditions:
    """check_preconditions with AND semantics."""

    def test_empty_conditions_true(self) -> None:
        """Empty list always passes."""
        assert check_preconditions([], {}) is True

    def test_all_pass_true(self) -> None:
        """All conditions met → True."""
        ctx = {"inventory": {"oak_log": 8}, "food": 10}
        assert check_preconditions(
            ["has_oak_log >= 3", "food < 15"], ctx
        ) is True

    def test_one_fails_false(self) -> None:
        """One condition fails → False (AND semantics)."""
        ctx = {"inventory": {"oak_log": 8}, "food": 10}
        assert check_preconditions(
            ["has_oak_log >= 10", "food < 15"], ctx
        ) is False

    def test_all_fail_false(self) -> None:
        """All conditions fail → False."""
        ctx = {"inventory": {"oak_log": 1}, "food": 18}
        assert check_preconditions(
            ["has_oak_log >= 10", "food < 5"], ctx
        ) is False

    def test_mixed_context_keys(self) -> None:
        """Mixture of has_X and standard keys works."""
        ctx = {"inventory": {"cobblestone": 40, "oak_log": 20}, "is_night": True, "health": 8}
        assert check_preconditions(
            ["has_cobblestone >= 32", "has_oak_log >= 16", "is_night", "health > 6"],
            ctx,
        ) is True

    def test_mixed_context_partial_fail(self) -> None:
        """Mixed conditions, one has_X fails."""
        ctx = {"inventory": {"cobblestone": 10}, "health": 8}
        assert check_preconditions(
            ["has_cobblestone >= 32", "health > 6"],
            ctx,
        ) is False

    def test_real_world_build_house_preconditions(self) -> None:
        """build_house preconditions (has_cobblestone >= 32, has_oak_log >= 16)."""
        ctx = {"inventory": {"cobblestone": 40, "oak_log": 20}}
        assert check_preconditions(
            ["has_cobblestone >= 32", "has_oak_log >= 16"], ctx
        ) is True

    def test_real_world_craft_armor_preconditions(self) -> None:
        """craft_armor preconditions (has_iron_ingot >= 24)."""
        ctx = {"inventory": {"iron_ingot": 30}}
        assert check_preconditions(
            ["has_iron_ingot >= 24"], ctx
        ) is True

    def test_real_world_craft_armor_fail(self) -> None:
        """craft_armor fails when iron_ingot < 24."""
        ctx = {"inventory": {"iron_ingot": 20}}
        assert check_preconditions(
            ["has_iron_ingot >= 24"], ctx
        ) is False


# ── SQLite Persistence Tests ─────────────────────────────────────────────────

class TestSkillLibraryPersistence:
    """Tests for SkillLibraryDB persistence layer."""

    async def test_save_and_load_from_db(self, tmp_path):
        """Save a skill, create a new library, load from DB — skill survives."""
        db_path = str(tmp_path / "test_skills.db")
        skill = Skill(
            id="persist_test",
            name="Persist Test",
            description="Tests persistence",
            steps=[SkillStep(name="mine", params={"block_type": "stone", "count": 1})],
            tags=["test"],
        )

        # Save to first library instance
        lib1 = SkillLibrary(db_path=db_path)
        await lib1.init_db()
        await lib1.save_skill(skill)
        await lib1.close_db()

        # Load from second library instance (simulates restart)
        lib2 = SkillLibrary(db_path=db_path)
        await lib2.init_db()

        loaded = await lib2.get_skill("persist_test")
        assert loaded is not None
        assert loaded.id == "persist_test"
        assert loaded.name == "Persist Test"
        assert loaded.steps[0].name == "mine"
        assert loaded.steps[0].params == {"block_type": "stone", "count": 1}
        assert loaded.tags == ["test"]
        await lib2.close_db()

    async def test_stats_persist_across_restart(self, tmp_path):
        """Success/failure counts persist across restarts."""
        import asyncio

        db_path = str(tmp_path / "stats_test.db")
        skill = Skill(id="stat_test", name="Stat Test", description="test")

        lib1 = SkillLibrary(db_path=db_path)
        await lib1.init_db()
        await lib1.save_skill(skill)
        await lib1.update_success("stat_test")
        await lib1.update_success("stat_test")
        await lib1.update_failure("stat_test")
        # Wait for async DB writes to complete
        await asyncio.sleep(0.1)
        await lib1.close_db()

        lib2 = SkillLibrary(db_path=db_path)
        await lib2.init_db()
        loaded = await lib2.get_skill("stat_test")
        assert loaded is not None
        assert loaded.success_count == 2
        assert loaded.fail_count == 1
        assert loaded.success_rate == pytest.approx(2 / 3)
        await lib2.close_db()

    async def test_predefined_skills_loaded_once(self, tmp_path):
        """Predefined skills are loaded once and not duplicated on re-init."""
        db_path = str(tmp_path / "predefined_test.db")
        lib = SkillLibrary(db_path=db_path)
        await lib.init_db()

        count1 = await lib.load_predefined_skills()
        assert count1 > 0  # Should load 9 predefined skills

        # Calling again should load 0 (already in DB)
        count2 = await lib.load_predefined_skills()
        assert count2 == 0

        await lib.close_db()

    async def test_remove_skill_persists(self, tmp_path):
        """Removed skills stay removed after restart."""
        db_path = str(tmp_path / "remove_test.db")
        skill = Skill(id="to_remove", name="Remove Me", description="test")

        lib1 = SkillLibrary(db_path=db_path)
        await lib1.init_db()
        await lib1.save_skill(skill)
        await lib1.remove_skill("to_remove")
        await lib1.close_db()

        lib2 = SkillLibrary(db_path=db_path)
        await lib2.init_db()
        loaded = await lib2.get_skill("to_remove")
        assert loaded is None
        await lib2.close_db()

    async def test_learned_skill_persists(self, tmp_path):
        """Learned skills (is_learned=True) persist with all metadata."""
        db_path = str(tmp_path / "learned_test.db")
        skill = Skill(
            id="learned_test",
            name="Learned Skill",
            description="Extracted from trace",
            steps=[SkillStep(name="craft", params={"recipe": "sword", "count": 1})],
            tags=["combat", "weapon"],
            is_learned=True,
            validated=False,
        )

        lib1 = SkillLibrary(db_path=db_path)
        await lib1.init_db()
        await lib1.add_learned(skill)
        await lib1.close_db()

        lib2 = SkillLibrary(db_path=db_path)
        await lib2.init_db()
        loaded = await lib2.get_skill("learned_test")
        assert loaded is not None
        assert loaded.is_learned is True
        assert loaded.validated is False
        assert loaded.tags == ["combat", "weapon"]
        await lib2.close_db()

    async def test_no_db_path_skips_persistence(self):
        """Without db_path, library works as pure in-memory store."""
        lib = SkillLibrary()
        skill = Skill(id="memory_only", name="Memory", description="test")
        await lib.save_skill(skill)
        loaded = await lib.get_skill("memory_only")
        assert loaded is not None
        # No DB to close

