"""
Tests for Skill Library
"""

import pytest
from datetime import datetime

from animetta.tools.minecraft.skill_library import Skill, SkillLibrary


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
        # Create a skill with low success rate and enough attempts
        skill = Skill(
            id="bad_skill",
            name="Bad Skill",
            description="This skill fails a lot",
            success_count=2,
            fail_count=8
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
