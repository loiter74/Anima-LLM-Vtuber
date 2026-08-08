"""Declarative Skill IR schema and static compiler tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.skill.ir import (
    SkillDefinition,
    SkillIRValidationError,
    SkillProgram,
    compile_skill_program,
)
from animetta.tools.minecraft.voyager.budget import BudgetUsage, ExecutionBudget

CAPABILITIES = {
    "collect": {
        "parameters_schema": {
            "type": "object",
            "properties": {
                "block_type": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["block_type", "count"],
            "additionalProperties": False,
        },
        "maximum_cost": BudgetUsage(max_actions=1, max_travel_distance=16, max_blocks_changed=4),
    }
}

BUDGET = ExecutionBudget(
    queue_timeout_ms=1_000,
    execution_timeout_ms=10_000,
    max_actions=8,
    max_strategy_attempts=4,
    max_travel_distance=128,
    max_blocks_changed=32,
    max_damage_taken=4,
)


def valid_program_payload() -> dict:
    return {
        "schema_version": "1",
        "name": "collect_logs",
        "parameters": [
            {"name": "target", "value_type": "string", "required": True},
            {"name": "count", "value_type": "integer", "required": True},
        ],
        "steps": [
            {
                "kind": "action",
                "step_id": "collect-1",
                "capability": "collect",
                "parameters": {
                    "block_type": {"kind": "goal_input", "name": "target"},
                    "count": {"kind": "goal_input", "name": "count"},
                },
            },
            {
                "kind": "branch",
                "step_id": "health-branch",
                "condition": {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "health"},
                    "right": {"kind": "literal", "value": 5},
                },
                "then_steps": [],
                "else_steps": [{"kind": "fail", "step_id": "unsafe", "code": "LOW_HEALTH"}],
            },
            {
                "kind": "repeat",
                "step_id": "bounded-retry",
                "max_iterations": 2,
                "steps": [],
            },
        ],
        "postconditions": [
            {
                "op": "gte",
                "left": {"kind": "observation", "path": "inventory.oak_log"},
                "right": {"kind": "goal_input", "name": "count"},
            }
        ],
        "portability": {"portable": True, "dimensions": ["minecraft:overworld"]},
    }


def test_skill_ir_is_normalized_content_addressed_and_statically_costed() -> None:
    program = SkillProgram.model_validate(valid_program_payload())
    compiled = compile_skill_program(program, capabilities=CAPABILITIES, budget=BUDGET)
    definition = SkillDefinition(
        definition_id="skill:collect_logs",
        name="collect_logs",
        description="Collect a bounded quantity of logs",
    )
    revision = compiled.to_revision(definition, source_command_id="command-1")

    assert compiled.static_cost.max_actions == 1
    assert compiled.static_cost.max_travel_distance == 16
    assert revision.revision_hash == program.canonical_hash
    assert revision.program is program


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda p: p.update({"code": "process.exit(0)"}), "extra"),
        (
            lambda p: p["steps"].__setitem__(
                0,
                {
                    "kind": "action",
                    "step_id": "collect-1",
                    "capability": {"kind": "goal_input", "name": "tool"},
                    "parameters": {},
                },
            ),
            "capability",
        ),
        (
            lambda p: p["steps"][0]["parameters"].update(
                {"count": {"kind": "goal_input", "name": "missing"}}
            ),
            "unbound goal input",
        ),
        (
            lambda p: p["steps"][0]["parameters"].update(
                {"count": {"kind": "literal", "value": "many"}}
            ),
            "expects integer",
        ),
        (
            lambda p: p["steps"].append({"kind": "call", "step_id": "recursive", "skill": "self"}),
            "union_tag_invalid",
        ),
        (
            lambda p: p["steps"].append({"kind": "repeat", "step_id": "forever", "steps": []}),
            "max_iterations",
        ),
        (
            lambda p: p["postconditions"].__setitem__(
                0,
                {
                    "op": "eq",
                    "left": {"kind": "observation", "path": "raw_bot.secret"},
                    "right": {"kind": "literal", "value": 1},
                },
            ),
            "forbidden observation field",
        ),
    ],
)
def test_invalid_or_unbounded_ir_is_rejected(mutation, match: str) -> None:
    payload = valid_program_payload()
    mutation(payload)
    try:
        program = SkillProgram.model_validate(payload)
        compile_skill_program(program, capabilities=CAPABILITIES, budget=BUDGET)
    except (ValidationError, SkillIRValidationError) as exc:
        assert match.lower() in str(exc).lower()
    else:
        raise AssertionError("invalid Skill IR must be rejected")


def test_static_cost_above_parent_budget_is_rejected() -> None:
    program = SkillProgram.model_validate(valid_program_payload())
    tiny = BUDGET.model_copy(update={"max_actions": 0})

    with pytest.raises(SkillIRValidationError, match="static cost exceeds"):
        compile_skill_program(program, capabilities=CAPABILITIES, budget=tiny)
