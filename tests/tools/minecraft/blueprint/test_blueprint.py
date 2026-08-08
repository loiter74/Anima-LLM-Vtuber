from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts.v2 import (
    Position,
    RegionBounds,
    RegionInspection,
    WorldIdentitySnapshot,
)
from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    BlueprintDimensions,
    BlueprintVerificationRules,
    PaletteEntry,
    RelativePlacement,
    SemanticFeature,
    StructureBlueprint,
    starter_shelter_blueprint,
)
from animetta.tools.minecraft.blueprint.verifier import BlueprintVerifier


def _small_blueprint() -> StructureBlueprint:
    return StructureBlueprint(
        blueprint_id="test-shelter-v1",
        dimensions=BlueprintDimensions(width=2, height=2, depth=1),
        palette={
            "shell": PaletteEntry(
                default_block="minecraft:oak_planks",
                allowed_blocks=("minecraft:oak_planks", "minecraft:cobblestone"),
            ),
            "door": PaletteEntry(
                default_block="minecraft:oak_door",
                allowed_blocks=("minecraft:oak_door",),
            ),
        },
        placements=(
            RelativePlacement(x=0, y=0, z=0, material="shell", role="wall"),
            RelativePlacement(x=1, y=0, z=0, material="door", role="door"),
            RelativePlacement(
                x=1,
                y=1,
                z=0,
                material="door",
                role="door",
                action_required=False,
                action_source=(1, 0, 0),
            ),
        ),
        semantic_features=(
            SemanticFeature(
                feature_id="entrance",
                kind="door",
                positions=((1, 0, 0), (1, 1, 0)),
            ),
        ),
        verification=BlueprintVerificationRules(
            required_feature_ids=frozenset({"entrance"}),
        ),
    )


def _world() -> WorldIdentitySnapshot:
    return WorldIdentitySnapshot(
        runtime_instance_id="runtime-instance-1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
    )


def _inspection(blocks: dict[str, str]) -> RegionInspection:
    return RegionInspection(
        inspection_id="inspection-1",
        correlation_id="correlation-region-1",
        runtime_instance_id="runtime-instance-1",
        world_identity=_world(),
        captured_at_ms=1_799_999_999_900,
        tick=200,
        observation_id="observation-region-1",
        observation_hash="e" * 64,
        bounds=RegionBounds(
            min=Position(x=10, y=64, z=20),
            max=Position(x=11, y=65, z=20),
        ),
        blocks=blocks,
        content_hash="4" * 64,
    )


def test_blueprint_schema_is_bounded_and_has_a_stable_canonical_hash() -> None:
    blueprint = _small_blueprint()
    reordered = StructureBlueprint.model_validate(
        {
            **blueprint.model_dump(mode="json"),
            "palette": dict(reversed(list(blueprint.model_dump(mode="json")["palette"].items()))),
        }
    )

    assert blueprint.volume == 4
    assert blueprint.canonical_hash == reordered.canonical_hash
    assert len(blueprint.canonical_hash) == 64

    payload = blueprint.model_dump(mode="json")
    payload["placements"][0]["x"] = 2
    with pytest.raises(ValidationError, match="outside blueprint dimensions"):
        StructureBlueprint.model_validate(payload)

    payload = blueprint.model_dump(mode="json")
    payload["placements"] = [payload["placements"][0]] * 4097
    with pytest.raises(ValidationError):
        StructureBlueprint.model_validate(payload)


def test_compiler_binds_origin_and_materials_with_exact_static_cost() -> None:
    compiled = BlueprintCompiler().compile(
        _small_blueprint(),
        BlueprintBinding(
            origin=(10, 64, 20),
            materials={"shell": "minecraft:cobblestone"},
        ),
    )

    assert [step.absolute_position for step in compiled.steps] == [(10, 64, 20), (11, 64, 20)]
    assert compiled.steps[0].parameters == {
        "block_type": "minecraft:cobblestone",
        "x": 10,
        "y": 64,
        "z": 20,
    }
    assert compiled.static_cost.max_actions == 2
    assert compiled.static_cost.max_blocks_changed == 3
    assert compiled.static_cost.resource_consumption == {
        "minecraft:cobblestone": 1,
        "minecraft:oak_door": 1,
    }

    with pytest.raises(ValueError, match="material binding is not approved"):
        BlueprintCompiler().compile(
            _small_blueprint(),
            BlueprintBinding(
                origin=(10, 64, 20),
                materials={"shell": "minecraft:diamond_block"},
            ),
        )


def test_approved_starter_shelter_compiles_to_finite_parameterized_place_steps() -> None:
    blueprint = starter_shelter_blueprint()
    compiled = BlueprintCompiler().compile(
        blueprint,
        BlueprintBinding(
            origin=(100, 70, -20),
            materials={"shell": "minecraft:cobblestone"},
        ),
    )

    assert blueprint.blueprint_id == "starter-shelter-v1"
    assert blueprint.verification.required_feature_ids == {
        "entrance",
        "roof",
        "interior-light",
        "bed",
    }
    assert 0 < len(compiled.steps) <= blueprint.volume
    assert all(step.capability == "place" for step in compiled.steps)
    assert compiled.bounds.min == Position(x=100, y=70, z=-20)
    assert compiled.bounds.max == Position(x=104, y=73, z=-16)


def test_compiled_starter_shelter_orders_every_step_after_a_solid_support() -> None:
    compiled = BlueprintCompiler().compile(
        starter_shelter_blueprint(),
        BlueprintBinding(origin=(4, 65, 4)),
    )
    placed: set[tuple[int, int, int]] = set()

    for step in compiled.steps:
        x, y, z = step.absolute_position
        neighbours = {
            (x - 1, y, z),
            (x + 1, y, z),
            (x, y - 1, z),
            (x, y + 1, z),
            (x, y, z - 1),
            (x, y, z + 1),
        }
        assert step.relative_position[1] == 0 or neighbours & placed, step.step_id
        placed.update(step.effect_positions)

    assert len(compiled.steps) == 83
    assert len(placed) == 85
    bed = next(step for step in compiled.steps if step.block_id == "minecraft:white_bed")
    assert bed.parameters["facing"] == "south"
    assert bed.effect_positions == ((6, 66, 6), (6, 66, 7))


def test_partial_resume_only_returns_air_backed_missing_steps_and_never_demolishes() -> None:
    compiled = BlueprintCompiler().compile(
        _small_blueprint(),
        BlueprintBinding(origin=(10, 64, 20)),
    )
    inspection = _inspection(
        {
            "10,64,20": "minecraft:air",
            "11,64,20": "minecraft:oak_door",
            "10,65,20": "minecraft:dirt",
            "11,65,20": "minecraft:dirt",
        }
    )

    verification = BlueprintVerifier().verify(compiled, inspection)
    resume = BlueprintVerifier().resume(compiled, inspection)

    assert verification.satisfied is False
    assert verification.missing_positions == ((10, 64, 20),)
    assert verification.conflicting_positions == ((11, 65, 20),)
    assert [step.absolute_position for step in resume.steps] == [(10, 64, 20)]
    assert resume.blocked_conflicts == ((11, 65, 20),)
