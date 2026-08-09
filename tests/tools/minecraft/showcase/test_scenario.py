from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.showcase.live import ReviewRconSetupExecutor
from animetta.tools.minecraft.showcase.scenario import (
    FilesystemScenarioEnvironment,
    PostStartMutationError,
    ScenarioPreparer,
    ScenarioSpec,
    SetupExecutionResult,
    compile_setup_operations,
    default_showcase_scenario,
    render_rcon_command,
)


def test_default_scenario_is_fixed_bounded_and_complete() -> None:
    scenario = default_showcase_scenario()

    assert scenario.world_seed == 8675309
    assert {zone.entity_type for zone in scenario.monster_zones} == {
        "minecraft:zombie",
        "minecraft:skeleton",
        "minecraft:spider",
    }
    assert len({zone.zone_id for zone in scenario.monster_zones}) == 3
    assert scenario.build_area.contains(scenario.build_origin)
    assert {item.item_id for item in scenario.loadout} >= {
        "minecraft:stone_sword",
        "minecraft:oak_planks",
        "minecraft:oak_door",
        "minecraft:white_bed",
        "minecraft:torch",
    }
    assert len(scenario.hidden_resources) == 3
    assert {resource.item_id for resource in scenario.hidden_resources} == {"minecraft:copper_ore"}
    assert all(resource.initially_known is False for resource in scenario.hidden_resources)
    assert scenario.fixed_time == "midnight"
    assert set(scenario.clean_stores) == {"mission", "discovery", "skill"}
    assert scenario.traversal_surface.minimum.y == scenario.traversal_surface.maximum.y
    standing_y = scenario.traversal_surface.minimum.y + 1
    assert scenario.bot_spawn.y == standing_y
    assert all(zone.spawn.y == standing_y for zone in scenario.monster_zones)
    assert scenario.build_origin.y == standing_y
    assert all(
        resource.position.y == scenario.traversal_surface.minimum.y
        for resource in scenario.hidden_resources
    )


def test_hidden_resource_setup_contains_three_separated_unlabelled_instances() -> None:
    scenario = default_showcase_scenario()
    copper = [
        operation
        for operation in compile_setup_operations(scenario)
        if operation.kind == "set_block" and operation.block_id == "minecraft:copper_ore"
    ]

    assert len(copper) == 3
    assert tuple(item.position for item in copper) == tuple(
        resource.position for resource in scenario.hidden_resources
    )
    positions = tuple(item.position for item in copper)
    assert all(
        (left.x - right.x) ** 2 + (left.z - right.z) ** 2 >= 4**2
        for index, left in enumerate(positions)
        for right in positions[index + 1 :]
    )
    assert all(
        set(type(resource).model_fields)
        == {
            "item_id",
            "position",
            "exploration_radius",
            "initially_known",
        }
        for resource in scenario.hidden_resources
    )


def test_scenario_rejects_hidden_resources_closer_than_four_blocks() -> None:
    payload = default_showcase_scenario().model_dump(mode="json")
    payload["hidden_resources"][1]["position"] = {
        **payload["hidden_resources"][0]["position"],
        "x": payload["hidden_resources"][0]["position"]["x"] - 1,
    }

    with pytest.raises(ValidationError, match="at least four blocks"):
        ScenarioSpec.model_validate(payload)


def test_monster_fixtures_are_stationary_until_bot_interaction() -> None:
    operations = compile_setup_operations(default_showcase_scenario())
    summons = [operation for operation in operations if operation.kind == "summon_entity"]

    assert len(summons) == 3
    assert all(operation.stationary is True for operation in summons)
    assert all(
        render_rcon_command(operation).endswith("{NoAI:1b,PersistenceRequired:1b}")
        for operation in summons
    )


def test_scenario_freezes_midnight_before_spawning_hostile_fixtures() -> None:
    operations = compile_setup_operations(default_showcase_scenario())
    operation_ids = [operation.operation_id for operation in operations]
    time_operation = next(
        operation for operation in operations if operation.operation_id == "set-fixed-time"
    )

    assert time_operation.kind == "set_world_time"
    assert render_rcon_command(time_operation) == "time set midnight"
    assert operation_ids.index("set-fixed-time") < operation_ids.index("spawn-zombie-zone")
    assert operation_ids.index("set-fixed-time") < operation_ids.index("spawn-skeleton-zone")


def test_scenario_rejects_raw_rcon_and_unbounded_extra_fields() -> None:
    payload = default_showcase_scenario().model_dump(mode="json")
    payload["rcon_commands"] = ["op arbitrary-player"]

    with pytest.raises(ValidationError):
        ScenarioSpec.model_validate(payload)


def test_scenario_rejects_a_combat_zone_outside_the_traversal_surface() -> None:
    payload = default_showcase_scenario().model_dump(mode="json")
    payload["monster_zones"][0]["spawn"]["x"] = 10_000
    payload["monster_zones"][0]["bounds"]["minimum"]["x"] = 9_997
    payload["monster_zones"][0]["bounds"]["maximum"]["x"] = 10_003

    with pytest.raises(ValidationError, match="traversal surface"):
        ScenarioSpec.model_validate(payload)


def test_closed_catalog_compiles_every_setup_effect_without_command_injection() -> None:
    scenario = default_showcase_scenario()
    operations = compile_setup_operations(scenario)

    assert {operation.kind for operation in operations} >= {
        "set_gamerule",
        "set_world_time",
        "force_load_region",
        "clear_inventory",
        "give_item",
        "clear_region",
        "fill_region",
        "summon_entity",
        "set_block",
        "teleport_player",
    }
    assert len({operation.operation_id for operation in operations}) == len(operations)
    arena_clear = next(
        operation for operation in operations if operation.operation_id == "clear-arena-headroom"
    )
    arena_floor = next(
        operation for operation in operations if operation.operation_id == "fill-arena-surface"
    )
    assert arena_clear.region.minimum.y == scenario.traversal_surface.minimum.y + 1
    assert arena_floor.region == scenario.traversal_surface
    assert arena_floor.block_id == "minecraft:stone"
    for operation in operations:
        command = render_rcon_command(operation)
        assert command
        assert ";" not in command
        assert "\n" not in command
        assert "\r" not in command


def test_setup_loads_action_chunks_before_spatial_mutations_and_repositions_last() -> None:
    operations = compile_setup_operations(default_showcase_scenario())
    operation_ids = [operation.operation_id for operation in operations]

    force_load_index = operation_ids.index("force-load-action-region")
    load_index = operation_ids.index("load-action-chunks")
    spatial_ids = (
        "clear-arena-headroom",
        "fill-arena-surface",
        "clear-build-area",
        "spawn-zombie-zone",
        "spawn-skeleton-zone",
        "spawn-spider-zone",
        "place-hidden-copper-01",
        "place-hidden-copper-02",
        "place-hidden-copper-03",
    )

    assert force_load_index < load_index
    assert all(load_index < operation_ids.index(operation_id) for operation_id in spatial_ids)
    assert operation_ids[-1] == "position-action-bot"

    force_load = operations[force_load_index]
    assert force_load.kind == "force_load_region"
    assert render_rcon_command(force_load) == "forceload add -20 -4 24 24"


class _RecordingExecutor:
    def __init__(self) -> None:
        self.operations = []

    async def execute(self, operation):
        self.operations.append(operation)
        return SetupExecutionResult(
            operation_id=operation.operation_id,
            outcome="success",
            response_code="OK",
        )


class _RecordingEnvironment:
    def __init__(self) -> None:
        self.calls = []

    async def prepare_disposable_world(self, scenario, run_id):
        self.calls.append(("world", run_id, scenario.world_seed))
        return "world/server.properties"

    async def create_clean_stores(self, run_id, store_names):
        self.calls.append(("stores", run_id, tuple(store_names)))
        return tuple(f"stores/{name}.sqlite3" for name in store_names)


async def test_prepare_records_excluded_receipts_and_clean_store_namespace() -> None:
    executor = _RecordingExecutor()
    environment = _RecordingEnvironment()
    preparer = ScenarioPreparer(
        executor=executor,
        environment=environment,
        now_ms=iter(range(100, 10_000)).__next__,
    )
    scenario = default_showcase_scenario()

    receipt = await preparer.prepare(scenario, run_id="showcase-run-001")

    assert receipt.scenario_hash == scenario.canonical_hash
    assert receipt.gameplay_evidence_eligible is False
    assert receipt.clean_store_namespace == "showcase-run-001"
    assert receipt.world_ref == "world/server.properties"
    assert receipt.store_refs == (
        "stores/mission.sqlite3",
        "stores/discovery.sqlite3",
        "stores/skill.sqlite3",
    )
    assert environment.calls == [
        ("world", "showcase-run-001", scenario.world_seed),
        ("stores", "showcase-run-001", scenario.clean_stores),
    ]
    assert tuple(item.operation_id for item in receipt.operations) == tuple(
        item.operation_id for item in executor.operations
    )
    assert all(item.outcome == "success" for item in receipt.operations)


async def test_mission_start_boundary_forbids_every_later_admin_mutation() -> None:
    executor = _RecordingExecutor()
    preparer = ScenarioPreparer(
        executor=executor,
        environment=_RecordingEnvironment(),
        now_ms=iter(range(100, 10_000)).__next__,
    )
    scenario = default_showcase_scenario()
    receipt = await preparer.prepare(scenario, run_id="showcase-run-002")
    boundary = preparer.start_mission(receipt, mission_id="adaptive-showcase-001")
    calls_before = len(executor.operations)

    with pytest.raises(PostStartMutationError, match="POST_START_MUTATION_FORBIDDEN"):
        await preparer.execute_setup_operation(compile_setup_operations(scenario)[0])

    assert len(executor.operations) == calls_before
    assert boundary.mission_id == "adaptive-showcase-001"
    assert preparer.run_valid is False
    assert preparer.state == "invalidated"


async def test_live_setup_rejects_rcon_textual_failure_even_when_process_exits_zero() -> None:
    class _Bridge:
        async def run_managed_setup(self, _command: str, *, request_id: str) -> dict:
            del request_id
            return {"outcome": "success", "output": "No player was found"}

    executor = ReviewRconSetupExecutor(_Bridge())  # type: ignore[arg-type]
    operation = next(
        item
        for item in compile_setup_operations(default_showcase_scenario())
        if item.operation_id == "load-action-chunks"
    )

    with pytest.raises(RuntimeError, match="SCENARIO_SETUP_RCON_FAILED"):
        await executor.execute(operation)


async def test_filesystem_environment_creates_fresh_seeded_world_and_empty_stores(
    tmp_path,
) -> None:
    environment = FilesystemScenarioEnvironment(tmp_path)
    scenario = default_showcase_scenario()

    world_ref = await environment.prepare_disposable_world(scenario, "showcase-run-003")
    store_refs = await environment.create_clean_stores("showcase-run-003", scenario.clean_stores)

    properties = (tmp_path / "showcase-run-003" / world_ref).read_text(encoding="utf-8")
    assert f"level-seed={scenario.world_seed}" in properties
    assert f"level-name={scenario.world_name}" in properties
    assert store_refs == (
        "stores/mission.sqlite3",
        "stores/discovery.sqlite3",
        "stores/skill.sqlite3",
    )
    assert all((tmp_path / "showcase-run-003" / ref).read_bytes() == b"" for ref in store_refs)

    with pytest.raises(FileExistsError):
        await environment.prepare_disposable_world(scenario, "showcase-run-003")
