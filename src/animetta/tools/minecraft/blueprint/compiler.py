"""Pure compiler from approved structure blueprints to bounded place steps."""

from __future__ import annotations

from animetta.tools.gamebot.contracts.v2 import Position, RegionBounds
from animetta.tools.minecraft.voyager.budget import BudgetUsage

from .models import (
    BlueprintBinding,
    CompiledBlueprint,
    CompiledFeature,
    CompiledPlacement,
    StructureBlueprint,
    resource_cost,
)


def _absolute(origin: tuple[int, int, int], relative: tuple[int, int, int]) -> tuple[int, int, int]:
    return (
        origin[0] + relative[0],
        origin[1] + relative[1],
        origin[2] + relative[2],
    )


def _face_neighbours(position: tuple[int, int, int]) -> tuple[tuple[int, int, int], ...]:
    x, y, z = position
    return (
        (x - 1, y, z),
        (x + 1, y, z),
        (x, y - 1, z),
        (x, y + 1, z),
        (x, y, z - 1),
        (x, y, z + 1),
    )


def _support_order(steps: list[CompiledPlacement]) -> tuple[CompiledPlacement, ...]:
    """Schedule placements only after a solid face-adjacent reference exists."""

    ordered: list[CompiledPlacement] = []
    placed: set[tuple[int, int, int]] = set()
    remaining = list(steps)
    while remaining:
        deferred: list[CompiledPlacement] = []
        progressed = False
        for step in remaining:
            grounded = step.relative_position[1] == 0
            supported = any(
                neighbour in placed for neighbour in _face_neighbours(step.absolute_position)
            )
            if not grounded and not supported:
                deferred.append(step)
                continue
            ordered.append(step)
            placed.update(step.effect_positions)
            progressed = True
        if not progressed:
            blocked = ", ".join(step.step_id for step in deferred[:8])
            raise ValueError(f"blueprint has unsupported placement topology: {blocked}")
        remaining = deferred
    return tuple(ordered)


def _horizontal_facing(
    source: tuple[int, int, int],
    derived: list[tuple[int, int, int]],
) -> str | None:
    if len(derived) != 1:
        return None
    dx = derived[0][0] - source[0]
    dy = derived[0][1] - source[1]
    dz = derived[0][2] - source[2]
    if dy != 0:
        return None
    return {
        (0, -1): "north",
        (0, 1): "south",
        (1, 0): "east",
        (-1, 0): "west",
    }.get((dx, dz))


class BlueprintCompiler:
    """Bind a finite blueprint without executing or inspecting the game runtime."""

    def compile(
        self,
        blueprint: StructureBlueprint,
        binding: BlueprintBinding,
    ) -> CompiledBlueprint:
        unknown = set(binding.materials) - set(blueprint.palette)
        if unknown:
            raise ValueError(f"unknown material binding: {sorted(unknown)!r}")
        materials = {
            key: binding.materials.get(key, entry.default_block)
            for key, entry in blueprint.palette.items()
        }
        for key, block_id in materials.items():
            if block_id not in blueprint.palette[key].allowed_blocks:
                raise ValueError(f"material binding is not approved: {key}={block_id}")

        expected_blocks: dict[str, str] = {}
        expected_roles: dict[str, str] = {}
        steps: list[CompiledPlacement] = []
        derived_by_source: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
        for placement in blueprint.placements:
            if placement.action_source is not None:
                derived_by_source.setdefault(placement.action_source, []).append(placement.position)
        for ordinal, placement in enumerate(blueprint.placements, start=1):
            absolute = _absolute(binding.origin, placement.position)
            key = ",".join(str(value) for value in absolute)
            block_id = materials[placement.material]
            expected_blocks[key] = block_id
            expected_roles[key] = placement.role
            if placement.action_required:
                derived = derived_by_source.get(placement.position, [])
                effect_positions = (placement.position, *derived)
                parameters: dict[str, str | int] = {
                    "block_type": block_id,
                    "x": absolute[0],
                    "y": absolute[1],
                    "z": absolute[2],
                }
                facing = _horizontal_facing(placement.position, derived)
                if facing is not None:
                    parameters["facing"] = facing
                steps.append(
                    CompiledPlacement(
                        step_id=f"place-{ordinal:04d}",
                        relative_position=placement.position,
                        absolute_position=absolute,
                        effect_positions=tuple(
                            _absolute(binding.origin, position) for position in effect_positions
                        ),
                        block_id=block_id,
                        role=placement.role,
                        parameters=parameters,
                    )
                )
        compiled_steps = _support_order(steps)
        origin_x, origin_y, origin_z = binding.origin
        maximum = (
            origin_x + blueprint.dimensions.width - 1,
            origin_y + blueprint.dimensions.height - 1,
            origin_z + blueprint.dimensions.depth - 1,
        )
        features = tuple(
            CompiledFeature(
                feature_id=feature.feature_id,
                kind=feature.kind,
                positions=tuple(
                    _absolute(binding.origin, position) for position in feature.positions
                ),
            )
            for feature in blueprint.semantic_features
        )
        return CompiledBlueprint(
            blueprint_id=blueprint.blueprint_id,
            blueprint_hash=blueprint.canonical_hash,
            origin=binding.origin,
            material_bindings=materials,
            bounds=RegionBounds(
                min=Position(x=origin_x, y=origin_y, z=origin_z),
                max=Position(x=maximum[0], y=maximum[1], z=maximum[2]),
            ),
            steps=compiled_steps,
            expected_blocks=expected_blocks,
            expected_roles=expected_roles,
            required_air=tuple(
                _absolute(binding.origin, position)
                for position in blueprint.verification.required_air
            ),
            features=features,
            required_feature_ids=blueprint.verification.required_feature_ids,
            static_cost=BudgetUsage(
                max_actions=len(compiled_steps),
                max_blocks_changed=sum(len(step.effect_positions) for step in compiled_steps),
                resource_consumption=resource_cost(compiled_steps),
            ),
        )
