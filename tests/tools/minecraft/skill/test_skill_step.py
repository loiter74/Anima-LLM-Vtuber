"""Unit tests for SkillStep dataclass."""


from animetta.tools.minecraft.skill.library import SkillStep


class TestSkillStepCreation:
    """Basic SkillStep construction."""

    def test_create_skill_step(self) -> None:
        step = SkillStep(name="goto", params={"x": 10, "y": 64, "z": -5})
        assert step.name == "goto"
        assert step.params == {"x": 10, "y": 64, "z": -5}
        assert step.preconditions == []
        assert step.timeout == 60.0
        assert step.retry == 0

    def test_create_with_all_fields(self) -> None:
        step = SkillStep(
            name="mine",
            params={"block_type": "stone", "count": 3},
            preconditions=["has_pickaxe"],
            timeout=30.0,
            retry=2,
        )
        assert step.name == "mine"
        assert step.params["block_type"] == "stone"
        assert step.preconditions == ["has_pickaxe"]
        assert step.timeout == 30.0
        assert step.retry == 2


class TestValidateParams:
    """SkillStep.validate_params() logic."""

    def test_validate_params_goto(self) -> None:
        step = SkillStep(name="goto", params={"x": 100, "y": 64, "z": 200})
        assert step.validate_params() == []

    def test_validate_params_goto_missing(self) -> None:
        step = SkillStep(name="goto", params={"x": 100, "z": 200})
        errors = step.validate_params()
        assert len(errors) == 1
        assert "y" in errors[0]

    def test_validate_params_unknown_type(self) -> None:
        step = SkillStep(name="fly", params={})
        errors = step.validate_params()
        assert len(errors) == 1
        assert "Unknown step type" in errors[0]
        assert "fly" in errors[0]

    def test_validate_params_collect_valid(self) -> None:
        step = SkillStep(name="collect", params={"block_type": "wood", "count": 5})
        assert step.validate_params() == []

    def test_validate_params_collect_default_count(self) -> None:
        step = SkillStep(name="collect", params={"block_type": "wood"})
        assert step.validate_params() == []

    def test_validate_params_collect_missing_block_type(self) -> None:
        step = SkillStep(name="collect", params={"count": 5})
        errors = step.validate_params()
        assert len(errors) == 1
        assert "block_type" in errors[0]

    def test_validate_params_type_mismatch(self) -> None:
        step = SkillStep(name="goto", params={"x": "not_an_int", "y": 64, "z": 0})
        errors = step.validate_params()
        assert len(errors) == 1
        assert "x" in errors[0]
        assert "int" in errors[0]

    def test_validate_params_wait(self) -> None:
        step = SkillStep(name="wait", params={"seconds": 5.0})
        assert step.validate_params() == []

    def test_validate_params_craft(self) -> None:
        step = SkillStep(name="craft", params={"recipe": "sword", "count": 1})
        assert step.validate_params() == []

    def test_validate_params_chat(self) -> None:
        step = SkillStep(name="chat", params={"message": "hello"})
        assert step.validate_params() == []


class TestSerialization:
    """to_dict / from_dict roundtrip."""

    def test_to_dict_from_dict(self) -> None:
        original = SkillStep(
            name="goto",
            params={"x": 10, "y": 64, "z": -5},
            preconditions=["is_day"],
            timeout=45.0,
            retry=1,
        )
        d = original.to_dict()
        restored = SkillStep.from_dict(d)

        assert restored.name == original.name
        assert restored.params == original.params
        assert restored.preconditions == original.preconditions
        assert restored.timeout == original.timeout
        assert restored.retry == original.retry

    def test_from_dict_defaults(self) -> None:
        d = {"name": "chat", "params": {"message": "hi"}}
        step = SkillStep.from_dict(d)
        assert step.name == "chat"
        assert step.params == {"message": "hi"}
        assert step.preconditions == []
        assert step.timeout == 60.0
        assert step.retry == 0

    def test_to_dict_structure(self) -> None:
        step = SkillStep(name="mine", params={"block_type": "stone"})
        d = step.to_dict()
        assert set(d.keys()) == {"name", "params", "preconditions", "timeout", "retry"}
