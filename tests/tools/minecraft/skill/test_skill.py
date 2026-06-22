"""Unit tests for Skill dataclass."""

import pytest

from animetta.tools.minecraft.skill_library import Skill, SkillStep


class TestSkillCreation:
    """Basic Skill construction."""

    def test_create_skill(self) -> None:
        skill = Skill(
            id="test-001",
            name="gather_wood",
            description="Collect wood logs",
        )
        assert skill.id == "test-001"
        assert skill.name == "gather_wood"
        assert skill.description == "Collect wood logs"
        assert skill.parameters == {}
        assert skill.preconditions == []
        assert skill.steps == []
        assert skill.category == ""
        assert skill.success_count == 0
        assert skill.fail_count == 0

    def test_skill_with_steps(self) -> None:
        steps = [
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="collect", params={"block_type": "log", "count": 5}),
        ]
        skill = Skill(
            id="test-002",
            name="gather_wood",
            description="Collect wood logs",
            steps=steps,
        )
        assert len(skill.steps) == 2
        assert skill.steps[0].name == "goto"
        assert skill.steps[1].name == "collect"

    def test_skill_category(self) -> None:
        skill = Skill(
            id="test-003",
            name="build_house",
            description="Build a simple house",
            category="building",
        )
        assert skill.category == "building"


class TestSuccessRate:
    """Skill.success_rate property."""

    def test_skill_success_rate_zero_executions(self) -> None:
        skill = Skill(id="s1", name="test", description="test")
        assert skill.success_rate == 0.0

    def test_skill_success_rate_all_success(self) -> None:
        skill = Skill(id="s1", name="test", description="test")
        skill.success_count = 10
        assert skill.success_rate == 1.0

    def test_skill_success_rate_all_failure(self) -> None:
        skill = Skill(id="s1", name="test", description="test")
        skill.fail_count = 5
        assert skill.success_rate == 0.0

    def test_skill_success_rate_mixed(self) -> None:
        skill = Skill(id="s1", name="test", description="test")
        skill.success_count = 3
        skill.fail_count = 7
        assert skill.success_rate == pytest.approx(0.3)

    def test_skill_success_rate_half(self) -> None:
        skill = Skill(id="s1", name="test", description="test")
        skill.success_count = 50
        skill.fail_count = 50
        assert skill.success_rate == pytest.approx(0.5)


class TestSerialization:
    """to_dict / from_dict roundtrip."""

    def test_to_dict_from_dict(self) -> None:
        steps = [
            SkillStep(name="goto", params={"x": 10, "y": 64, "z": 20}),
            SkillStep(name="mine", params={"block_type": "stone", "count": 3}),
        ]
        original = Skill(
            id="roundtrip-1",
            name="mine_stone",
            description="Mine 3 stone blocks",
            parameters={"location": "cave"},
            preconditions=["has_pickaxe"],
            steps=steps,
            category="mining",
            postconditions=["has_stone"],
            success_count=5,
            fail_count=2,
            avg_duration=12.5,
            last_used="2026-06-19T10:00:00",
            tags=["mining", "stone"],
        )

        d = original.to_dict()
        restored = Skill.from_dict(d)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.parameters == original.parameters
        assert restored.preconditions == original.preconditions
        assert len(restored.steps) == 2
        assert restored.steps[0].name == "goto"
        assert restored.steps[1].name == "mine"
        assert restored.category == original.category
        assert restored.postconditions == original.postconditions
        assert restored.success_count == original.success_count
        assert restored.fail_count == original.fail_count
        assert restored.avg_duration == original.avg_duration
        assert restored.last_used == original.last_used
        assert restored.tags == original.tags

    def test_to_dict_from_dict_empty(self) -> None:
        original = Skill(id="e1", name="empty", description="no steps")
        d = original.to_dict()
        restored = Skill.from_dict(d)
        assert restored.id == "e1"
        assert restored.steps == []

    def test_to_dict_steps_are_dicts(self) -> None:
        skill = Skill(
            id="s1",
            name="test",
            description="test",
            steps=[SkillStep(name="chat", params={"message": "hi"})],
        )
        d = skill.to_dict()
        assert isinstance(d["steps"], list)
        assert isinstance(d["steps"][0], dict)
        assert d["steps"][0]["name"] == "chat"
