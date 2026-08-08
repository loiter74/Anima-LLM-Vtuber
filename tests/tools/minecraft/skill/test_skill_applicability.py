from __future__ import annotations

from importlib import import_module

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.skill.ir import (
    SkillDefinition,
    SkillProgram,
    SkillRevision,
)
from animetta.tools.minecraft.skill.revision_store import SkillRevisionStore
from animetta.tools.minecraft.skill.trust import SkillEnvironmentTrust
from animetta.tools.minecraft.voyager.budget import BudgetUsage


def _module():
    return import_module("animetta.tools.minecraft.skill.applicability")


def _revision() -> tuple[SkillDefinition, SkillRevision]:
    program = SkillProgram.model_validate(
        {
            "name": "acquire_resource",
            "parameters": [
                {"name": "resource", "value_type": "string"},
                {"name": "count", "value_type": "integer"},
            ],
            "steps": [
                {
                    "kind": "action",
                    "step_id": "collect-resource",
                    "capability": "collect",
                    "parameters": {
                        "block_type": {"kind": "goal_input", "name": "resource"},
                        "count": {"kind": "goal_input", "name": "count"},
                    },
                }
            ],
            "postconditions": [
                {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "inventory.target"},
                    "right": {"kind": "goal_input", "name": "count"},
                }
            ],
        }
    )
    definition = SkillDefinition(
        definition_id="acquire-resource",
        name="acquire_resource",
        description="Acquire a bounded resource quantity.",
    )
    return definition, SkillRevision(
        definition_id=definition.definition_id,
        revision_hash=program.canonical_hash,
        program=program,
        static_cost=BudgetUsage(max_actions=2, max_travel_distance=32),
        source_command_id="learn-command-001",
    )


def _applicability(module, revision_hash: str):
    return module.SkillApplicability(
        schema_version="1",
        revision_hash=revision_hash,
        intents=frozenset({"acquire"}),
        target_patterns=(module.TargetPattern(kind="prefix", value="minecraft:"),),
        parameter_bindings=(
            module.ParameterBinding(parameter="resource", source="goal_target"),
            module.ParameterBinding(parameter="count", source="goal_quantity"),
        ),
        required_capabilities=frozenset({"collect"}),
        discovery_prerequisites=(
            module.DiscoveryPrerequisite(
                fact_kind="block",
                fact_key="minecraft:copper_ore",
                minimum_state="observed",
            ),
        ),
        technology_prerequisites=frozenset({"stone_tools"}),
    )


def test_applicability_is_immutable_content_addressed_and_closed() -> None:
    module = _module()
    _, revision = _revision()
    applicability = _applicability(module, revision.revision_hash)

    assert applicability.applicability_hash == applicability.model_copy().applicability_hash
    assert applicability.parameter_bindings[0].source == "goal_target"
    with pytest.raises(ValidationError):
        applicability.intents = frozenset({"combat"})
    with pytest.raises(ValidationError):
        module.TargetPattern(kind="regex", value=".*")
    with pytest.raises(ValidationError, match="duplicate parameter binding"):
        type(applicability).model_validate(
            {
                **applicability.model_dump(),
                "parameter_bindings": (
                    applicability.parameter_bindings[0],
                    applicability.parameter_bindings[0],
                ),
            }
        )


async def test_store_adds_applicability_without_rewriting_revision_or_trust_history(
    tmp_path,
) -> None:
    module = _module()
    definition, revision = _revision()
    applicability = _applicability(module, revision.revision_hash)
    trust = SkillEnvironmentTrust.trusted(
        revision.revision_hash,
        "e" * 64,
        successes=3,
        expected_cost=2,
    )
    store = SkillRevisionStore(tmp_path / "skills.db")
    await store.connect()
    try:
        await store.save_revision(definition, revision)
        await store.record_validation(
            trust,
            policy_report={"valid": True},
            learning_evidence=("receipt:learning-001",),
            validation_evidence=("receipt:validation-001",),
        )
        await store.save_applicability(applicability)

        loaded = await store.load_applicability(revision.revision_hash)
        revisions, trusts = await store.load_live_catalog(environment_fingerprint="e" * 64)
    finally:
        await store.close()

    assert loaded == applicability
    assert revisions == {revision.revision_hash: revision}
    assert trusts == [trust]


async def test_applicability_store_rejects_unknown_revision_hash(tmp_path) -> None:
    module = _module()
    store = SkillRevisionStore(tmp_path / "skills.db")
    await store.connect()
    try:
        with pytest.raises(ValueError, match="UNKNOWN_SKILL_REVISION"):
            await store.save_applicability(_applicability(module, "f" * 64))
    finally:
        await store.close()
