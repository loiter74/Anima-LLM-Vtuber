"""Real E2E harness keeps technology progress separate from skill trust."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import scripts.voyager_real_e2e as harness


def test_locate_biome_output_yields_fresh_fixture_center() -> None:
    output = "The nearest minecraft:forest is at [20352, 100, 20192] (400 blocks away)"

    parser = getattr(harness, "parse_locate_coordinates", None)

    assert parser is not None
    assert parser(output) == (20352, 20192)


def test_fixture_search_origins_are_chunk_regions_apart() -> None:
    origin = getattr(harness, "fixture_search_origin", None)

    assert origin is not None
    first = origin(1)
    second = origin(2)

    assert abs(second[0] - first[0]) >= 2048
    assert abs(second[1] - first[1]) >= 2048


def test_fixture_uses_lowland_oak_biome_for_bounded_descent() -> None:
    assert getattr(harness, "FIXTURE_BIOME", None) == "minecraft:forest"
    assert getattr(harness, "FIXTURE_REGION_ATTEMPTS", None) == 8
    assert getattr(harness, "FIXTURE_MAX_ATTEMPTS", None) == 8


def test_natural_ground_check_only_accepts_successful_grass_probe() -> None:
    checker = getattr(harness, "natural_ground_check_passed", None)

    assert checker is not None
    assert checker("VoyagerAudit has 0 experience points") is True
    assert checker("Test failed") is False
    assert checker("") is False


def test_entity_position_output_yields_surface_height() -> None:
    parser = getattr(harness, "parse_entity_y", None)

    assert parser is not None
    output = "VoyagerAudit has the following entity data: [81664.5d, 111.0d, -41636.25d]"
    assert parser(output) == 111.0


async def test_fixture_positioning_retries_until_natural_ground(monkeypatch) -> None:
    position = getattr(harness, "position_player_on_natural_ground", None)
    assert position is not None

    outputs = iter(
        [
            "Spread 1 entities around 20352.0, 20192.0",
            "VoyagerAudit has 0 experience points",
            "VoyagerAudit has the following entity data: [20352.5d, 111.0d, 20192.5d]",
            "Spread 1 entities around 20352.0, 20192.0",
            "VoyagerAudit has 0 experience points",
            "VoyagerAudit has the following entity data: [20354.5d, 64.0d, 20194.5d]",
        ]
    )
    commands: list[str] = []

    def fake_rcon(command: str) -> str:
        commands.append(command)
        return next(outputs)

    monkeypatch.setattr(harness, "rcon", fake_rcon)
    monkeypatch.setattr(harness.asyncio, "sleep", AsyncMock())
    audit: list[dict[str, str]] = []

    await position(20352, 20192, audit, max_attempts=3)

    assert len([command for command in commands if command.startswith("spreadplayers")]) == 2
    assert (
        len(
            [command for command in commands if "if block ~ ~-1 ~ minecraft:grass_block" in command]
        )
        == 2
    )
    assert (
        len([command for command in commands if "data get entity VoyagerAudit Pos" in command]) == 2
    )
    assert audit[-1]["output"].endswith("[20354.5d, 64.0d, 20194.5d]")


def test_real_progression_uses_production_action_timeout() -> None:
    assert getattr(harness, "REAL_ACTION_TIMEOUT_SECONDS", None) == 180.0


def test_real_cobblestone_strategy_uses_audited_safe_descent() -> None:
    code = harness.StrategyGenerator.STRATEGIES["cobblestone"]

    assert "mine_shaft(50, 1)" in code
    assert "collect('cobblestone'" not in code


def test_real_cobblestone_strategy_rebuilds_wooden_pickaxe_before_descent() -> None:
    code = harness.StrategyGenerator.STRATEGIES["cobblestone"]

    assert "collect('oak_log'" in code
    assert "craft('wooden_pickaxe', 1)" in code
    assert code.index("craft('wooden_pickaxe', 1)") < code.index("mine_shaft")


def test_real_cobblestone_strategy_prepares_early_survival_weapon() -> None:
    code = harness.StrategyGenerator.STRATEGIES["cobblestone"]

    assert "craft('wooden_sword', 1)" in code
    assert code.index("craft('wooden_sword', 1)") < code.index("mine_shaft")


async def test_real_cobblestone_strategy_reuses_observed_wooden_tools() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"wooden_pickaxe": 1, "wooden_sword": 1})
    node = SimpleNamespace(id="cobblestone")

    code = await generator.generate(node=node, observation=observation)

    assert code == "await mine_shaft(50, 1);"


async def test_progression_accepts_independent_frontier_nodes_out_of_order() -> None:
    class FakeProgress:
        unlocked_nodes: frozenset[str] = frozenset()

    class FakeSession:
        def __init__(self) -> None:
            self.progress = FakeProgress()
            self._outcomes = iter(
                [
                    SimpleNamespace(
                        status="candidate",
                        node_id="furnace",
                        model_dump=lambda **_: {
                            "status": "candidate",
                            "node_id": "furnace",
                        },
                    ),
                    SimpleNamespace(
                        status="failed",
                        node_id="stone_pickaxe",
                        model_dump=lambda **_: {
                            "status": "failed",
                            "node_id": "stone_pickaxe",
                        },
                    ),
                    SimpleNamespace(
                        status="candidate",
                        node_id="stone_pickaxe",
                        model_dump=lambda **_: {
                            "status": "candidate",
                            "node_id": "stone_pickaxe",
                        },
                    ),
                ]
            )

        async def run_once(self):
            outcome = next(self._outcomes)
            if outcome.status == "candidate":
                self.progress.unlocked_nodes |= {outcome.node_id}
            return outcome

    outcomes, completed = await harness.advance_progression(
        FakeSession(),
        ["stone_pickaxe", "furnace"],
        max_cycles=3,
    )

    assert completed is True
    assert [outcome["node_id"] for outcome in outcomes] == [
        "furnace",
        "stone_pickaxe",
        "stone_pickaxe",
    ]


async def test_real_pickaxe_strategy_reuses_observed_sticks() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"stick": 14, "iron_ingot": 8})
    node = SimpleNamespace(id="iron_pickaxe")

    code = await generator.generate(node=node, observation=observation)

    assert "craft('stick'" not in code
    assert code == "await craft('iron_pickaxe', 1);"


async def test_real_stone_pickaxe_strategy_replenishes_missing_cobblestone() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"stick": 4, "cobblestone": 1, "wooden_pickaxe": 1})
    node = SimpleNamespace(id="stone_pickaxe")

    code = await generator.generate(node=node, observation=observation)

    assert code == "await mine_shaft(50, 2); await craft('stone_pickaxe', 1);"


async def test_real_stone_pickaxe_strategy_recovers_tools_after_death() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={})
    node = SimpleNamespace(id="stone_pickaxe")

    code = await generator.generate(node=node, observation=observation)

    assert "collect('oak_log', 3)" in code
    assert "craft('crafting_table', 1)" in code
    assert "craft('wooden_pickaxe', 1)" in code
    assert "craft('wooden_sword', 1)" in code
    assert "mine_shaft(50, 3)" in code
    assert code.endswith("await craft('stone_pickaxe', 1);")


def test_material_recovery_capabilities_are_authorized_by_tech_graph() -> None:
    graph = harness.build_survival_tech_graph()

    assert "collect" in graph.get("stone_pickaxe").allowed_capabilities
    assert "mine_shaft" in graph.get("stone_pickaxe").allowed_capabilities
    assert "collect" in graph.get("furnace").allowed_capabilities
    assert "collect" in graph.get("iron_pickaxe").allowed_capabilities
    assert "smelt" in graph.get("iron_pickaxe").allowed_capabilities


async def test_real_iron_pickaxe_strategy_replenishes_its_own_iron() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"iron_ingot": 1, "stick": 2})
    node = SimpleNamespace(id="iron_pickaxe")

    code = await generator.generate(node=node, observation=observation)

    assert code == (
        "await collect('raw_iron', 2); await collect('coal', 1); "
        "await smelt('raw_iron', 'coal', 2); await craft('iron_pickaxe', 1);"
    )


def test_real_iron_strategy_descends_before_collecting_ore() -> None:
    code = harness.StrategyGenerator.STRATEGIES["iron_ingot"]

    assert "mine_shaft(55, 11)" in code
    assert code.index("mine_shaft") < code.index("collect('raw_iron'")
    assert "collect('raw_iron', 1)" in code
    assert "smelt('raw_iron', 'coal', 1)" in code


def test_real_iron_strategy_collects_support_blocks_before_descent() -> None:
    code = harness.StrategyGenerator.STRATEGIES["iron_ingot"]

    support = "mine_shaft(55, 11)"
    assert support in code
    assert code.index(support) < code.index("craft('furnace', 1)")


def test_real_iron_strategy_rebuilds_full_durability_pickaxe_before_descent() -> None:
    code = harness.StrategyGenerator.STRATEGIES["iron_ingot"]

    support = "mine_shaft(55, 11)"
    tool_recovery = "craft('stone_pickaxe', 1)"
    assert tool_recovery in code
    assert code.index(support) < code.index(tool_recovery) < code.index("collect('raw_iron'")


def test_real_iron_strategy_rebuilds_pickaxe_materials_on_every_retry() -> None:
    code = harness.StrategyGenerator.STRATEGIES["iron_ingot"]

    wood_recovery = "collect('oak_log', 3)"
    stick_recovery = "craft('stick', 1)"
    wooden_tool_recovery = "craft('wooden_pickaxe', 1)"
    tool_recovery = "craft('stone_pickaxe', 1)"
    assert wood_recovery in code
    assert stick_recovery in code
    assert wooden_tool_recovery in code
    assert (
        code.index(wood_recovery)
        < code.index(stick_recovery)
        < code.index(wooden_tool_recovery)
        < code.index(tool_recovery)
    )


async def test_real_iron_strategy_recovers_full_toolchain_after_death() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={})
    node = SimpleNamespace(id="iron_ingot")

    code = await generator.generate(node=node, observation=observation)

    required_steps = [
        "collect('oak_log', 3)",
        "craft('crafting_table', 1)",
        "craft('wooden_pickaxe', 1)",
        "craft('wooden_sword', 1)",
        "mine_shaft(55, 11)",
        "craft('stone_pickaxe', 1)",
        "craft('furnace', 1)",
        "collect('raw_iron', 1)",
        "collect('coal', 1)",
        "smelt('raw_iron', 'coal', 1)",
    ]
    positions = [code.index(step) for step in required_steps]
    assert positions == sorted(positions)


async def test_real_iron_strategy_reuses_observed_tool_and_support() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(
        inventory={
            "stone_pickaxe": 1,
            "stone_sword": 1,
            "cobblestone": 16,
            "stick": 2,
        }
    )
    node = SimpleNamespace(id="iron_ingot")

    code = await generator.generate(node=node, observation=observation)

    assert "collect('oak_log'" not in code
    assert "collect('cobblestone'" not in code
    assert "craft('stone_pickaxe'" not in code
    assert code.startswith("await mine_shaft(55);")


async def test_real_iron_strategy_prepares_stone_sword_for_long_search() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"stone_pickaxe": 1, "cobblestone": 16, "stick": 2})
    node = SimpleNamespace(id="iron_ingot")

    code = await generator.generate(node=node, observation=observation)

    assert "craft('stone_sword', 1)" in code
    assert code.index("craft('stone_sword', 1)") < code.index("mine_shaft(55)")


async def test_real_iron_strategy_closes_receipt_chain_after_timed_out_smelt() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"iron_ingot": 4, "raw_iron": 2, "coal": 3})
    node = SimpleNamespace(id="iron_ingot")

    code = await generator.generate(node=node, observation=observation)

    assert code == ("await collect('cobblestone', 1); await smelt('raw_iron', 'coal', 1);")


async def test_real_furnace_strategy_collects_only_missing_cobblestone() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"cobblestone": 5})
    node = SimpleNamespace(id="furnace")

    code = await generator.generate(node=node, observation=observation)

    assert code == "await collect('cobblestone', 3); await craft('furnace', 1);"


def test_candidate_outcome_completes_node_only_when_unlock_record_exists() -> None:
    completed = getattr(harness, "technology_node_completed", None)

    assert completed is not None
    candidate = SimpleNamespace(status="candidate", node_id="wooden_pickaxe")
    assert completed(candidate, "wooden_pickaxe", {"wooden_pickaxe"}) is True
    assert completed(candidate, "wooden_pickaxe", set()) is False
    assert completed(candidate, "cobblestone", {"wooden_pickaxe"}) is False


def test_failed_or_discovery_outcome_never_completes_node() -> None:
    completed = getattr(harness, "technology_node_completed", None)

    assert completed is not None
    for status in ("failed", "discovery"):
        outcome = SimpleNamespace(status=status, node_id="wooden_pickaxe")
        assert completed(outcome, "wooden_pickaxe", {"wooden_pickaxe"}) is False
