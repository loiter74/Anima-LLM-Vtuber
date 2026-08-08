from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts.v2 import (
    AdvancementObservedEvent,
    CombatTerminalEvidence,
    DiscoverableBlock,
    DiscoverableEntity,
    EnvironmentProfile,
    Observation,
    Position,
    RegionBounds,
    RegionInspection,
    RegionInspectionRequest,
    WorldIdentitySnapshot,
)


def _profile() -> EnvironmentProfile:
    return EnvironmentProfile(
        runtime_protocol="2.0",
        minecraft_version="1.21.1",
        capability_schema_digest="a" * 64,
        skill_api_version="1",
        policy_version="1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
        modset_digest="d" * 64,
    )


def _world() -> WorldIdentitySnapshot:
    return WorldIdentitySnapshot(
        runtime_instance_id="runtime-instance-1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
    )


def _observation() -> Observation:
    return Observation(
        observation_id="observation-1",
        correlation_id="correlation-observe-1",
        runtime_instance_id="runtime-instance-1",
        captured_at_ms=1_799_999_999_000,
        tick=42,
        action_sequence=7,
        content_hash="e" * 64,
        profile=_profile(),
        world_identity=_world(),
        position=Position(x=0, y=64, z=0),
        health=20,
        food=20,
    )


def test_observation_projects_discoverable_fields_with_exact_world_identity() -> None:
    observation = Observation.model_validate(
        {
            **_observation().model_dump(mode="json"),
            "world_identity": _world().model_dump(mode="json"),
            "biome": "minecraft:plains",
            "active_advancements": ("minecraft:story/root",),
            "visible_blocks": (
                DiscoverableBlock(
                    block_id="minecraft:copper_ore",
                    position=Position(x=3, y=62, z=4),
                ),
            ),
            "visible_entities": (
                DiscoverableEntity(
                    entity_id="entity-zombie-001",
                    entity_type="minecraft:zombie",
                    position=Position(x=8, y=64, z=2),
                    health=20,
                ),
            ),
        }
    )

    assert observation.visible_blocks[0].block_id == "minecraft:copper_ore"
    assert observation.active_advancements == ("minecraft:story/root",)
    invalid = observation.model_dump(mode="json")
    invalid["world_identity"]["world_identity_hash"] = "d" * 64
    with pytest.raises(ValidationError, match="world identity"):
        Observation.model_validate(invalid)


def test_combat_terminal_evidence_has_typed_target_outcome_and_health_ticks() -> None:
    combat = CombatTerminalEvidence(
        target_entity_id="entity-zombie-001",
        target_entity_type="minecraft:zombie",
        outcome="defeated",
        bot_health_before=20,
        bot_health_after=17,
        target_health_before=20,
        target_health_after=0,
        started_tick=100,
        finished_tick=124,
    )

    assert combat.outcome == "defeated"
    with pytest.raises(ValidationError, match="defeated combat target"):
        type(combat).model_validate(
            {
                **combat.model_dump(),
                "target_health_after": 3,
            }
        )


def test_region_inspection_is_read_only_bounded_and_position_checked() -> None:
    bounds = RegionBounds(
        min=Position(x=0, y=60, z=0),
        max=Position(x=3, y=63, z=3),
    )
    request = RegionInspectionRequest(
        transport_id="transport-region-1",
        command_id="command-region-1",
        step_id="inspect-shelter",
        correlation_id="correlation-region-1",
        runtime_instance_id="runtime-instance-1",
        bounds=bounds,
        maximum_volume=64,
        deadline_ms=1_800_000_000_000,
    )
    result = RegionInspection(
        inspection_id="inspection-1",
        correlation_id=request.correlation_id,
        runtime_instance_id=request.runtime_instance_id,
        world_identity=_world(),
        captured_at_ms=1_799_999_999_900,
        tick=200,
        observation_id="observation-region-001",
        observation_hash="e" * 64,
        bounds=bounds,
        blocks={"0,60,0": "minecraft:oak_planks"},
        content_hash="a" * 64,
    )

    assert request.bounds.volume == 64
    assert result.observation_id == "observation-region-001"
    assert result.blocks["0,60,0"] == "minecraft:oak_planks"
    with pytest.raises(ValidationError, match="maximum region volume"):
        RegionInspectionRequest.model_validate(
            {**request.model_dump(mode="json"), "maximum_volume": 63}
        )
    with pytest.raises(ValidationError, match="outside inspected region"):
        RegionInspection.model_validate(
            {
                **result.model_dump(mode="json"),
                "blocks": {"9,60,0": "minecraft:stone"},
            }
        )


def test_advancement_event_is_world_scoped_version_adapter_evidence() -> None:
    event = AdvancementObservedEvent(
        event_id="advancement-event-001",
        runtime_instance_id="runtime-instance-1",
        world_identity=_world(),
        advancement_id="minecraft:story/mine_stone",
        action="add",
        observation_id="observation-advancement-001",
        observation_hash="e" * 64,
        observed_at_ms=1_799_999_999_950,
        tick=220,
        source="version_adapter",
        content_hash="f" * 64,
    )

    assert event.world_identity.world_identity_hash == _profile().world_identity_hash
    assert event.action == "add"
    assert event.observation_hash == "e" * 64
    assert event.source == "version_adapter"
