"""Approved finite starter shelter blueprint."""

from __future__ import annotations

from .models import (
    BlueprintDimensions,
    BlueprintVerificationRules,
    PaletteEntry,
    RelativePlacement,
    SemanticFeature,
    StructureBlueprint,
)


def starter_shelter_blueprint() -> StructureBlueprint:
    placements: list[RelativePlacement] = []
    for x in range(5):
        for z in range(5):
            placements.append(RelativePlacement(x=x, y=0, z=z, material="shell", role="floor"))
            placements.append(RelativePlacement(x=x, y=3, z=z, material="shell", role="roof"))
    for y in (1, 2):
        for x in range(5):
            for z in range(5):
                if x not in {0, 4} and z not in {0, 4}:
                    continue
                if x == 2 and z == 0:
                    continue
                placements.append(RelativePlacement(x=x, y=y, z=z, material="shell", role="wall"))
    placements.extend(
        (
            RelativePlacement(x=2, y=1, z=0, material="door", role="door"),
            RelativePlacement(
                x=2,
                y=2,
                z=0,
                material="door",
                role="door",
                action_required=False,
                action_source=(2, 1, 0),
            ),
            RelativePlacement(x=1, y=1, z=2, material="light", role="light"),
            RelativePlacement(x=2, y=1, z=2, material="bed", role="bed"),
            RelativePlacement(
                x=2,
                y=1,
                z=3,
                material="bed",
                role="bed",
                action_required=False,
                action_source=(2, 1, 2),
            ),
        )
    )
    roof = tuple((x, 3, z) for x in range(5) for z in range(5))
    return StructureBlueprint(
        blueprint_id="starter-shelter-v1",
        dimensions=BlueprintDimensions(width=5, height=4, depth=5),
        palette={
            "shell": PaletteEntry(
                default_block="minecraft:oak_planks",
                allowed_blocks=(
                    "minecraft:oak_planks",
                    "minecraft:spruce_planks",
                    "minecraft:birch_planks",
                    "minecraft:cobblestone",
                ),
            ),
            "door": PaletteEntry(
                default_block="minecraft:oak_door",
                allowed_blocks=("minecraft:oak_door",),
            ),
            "light": PaletteEntry(
                default_block="minecraft:torch",
                allowed_blocks=("minecraft:torch", "minecraft:lantern"),
            ),
            "bed": PaletteEntry(
                default_block="minecraft:white_bed",
                allowed_blocks=("minecraft:white_bed",),
            ),
        },
        placements=tuple(placements),
        semantic_features=(
            SemanticFeature(
                feature_id="entrance",
                kind="door",
                positions=((2, 1, 0), (2, 2, 0)),
            ),
            SemanticFeature(feature_id="roof", kind="roof", positions=roof),
            SemanticFeature(
                feature_id="interior-light",
                kind="light",
                positions=((1, 1, 2),),
            ),
            SemanticFeature(
                feature_id="bed",
                kind="bed",
                positions=((2, 1, 2), (2, 1, 3)),
            ),
        ),
        verification=BlueprintVerificationRules(
            required_feature_ids=frozenset({"entrance", "roof", "interior-light", "bed"})
        ),
    )
