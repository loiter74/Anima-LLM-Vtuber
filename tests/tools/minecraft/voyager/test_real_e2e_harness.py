"""Real E2E harness keeps technology progress separate from skill trust."""

from __future__ import annotations

from types import SimpleNamespace

import scripts.voyager_real_e2e as harness


def test_locate_biome_output_yields_fresh_fixture_center() -> None:
    output = (
        "The nearest minecraft:forest is at [20352, 100, 20192] "
        "(400 blocks away)"
    )

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


def test_real_progression_uses_production_action_timeout() -> None:
    assert getattr(harness, "REAL_ACTION_TIMEOUT_SECONDS", None) == 180.0


def test_real_cobblestone_strategy_uses_audited_safe_descent() -> None:
    code = harness.StrategyGenerator.STRATEGIES["cobblestone"]

    assert "mine_shaft" in code
    assert "collect('cobblestone'" not in code


async def test_real_pickaxe_strategy_reuses_observed_sticks() -> None:
    generator = harness.StrategyGenerator()
    observation = SimpleNamespace(inventory={"stick": 14, "iron_ingot": 8})
    node = SimpleNamespace(id="iron_pickaxe")

    code = await generator.generate(node=node, observation=observation)

    assert "craft('stick'" not in code
    assert code == "await craft('iron_pickaxe', 1);"


def test_real_iron_strategy_descends_before_collecting_ore() -> None:
    code = harness.StrategyGenerator.STRATEGIES["iron_ingot"]

    assert code.index("mine_shaft") < code.index("collect('raw_iron'")
    assert "smelt('raw_iron'" in code


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
