"""Evidence-driven Minecraft technology progression."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from animetta.tools.gamebot.contracts import (
    ActionOutcome,
    ActionReceipt,
    GameBotObservation,
)


def _tech():
    return importlib.import_module("animetta.tools.minecraft.voyager.tech_graph")


def _observation(
    observation_id: str,
    inventory: dict[str, int],
    *,
    correlation_id: str | None = None,
):
    return GameBotObservation(
        observation_id=observation_id,
        correlation_id=correlation_id or f"corr-{observation_id}",
        runtime_id="runtime-1",
        captured_at=datetime(2026, 7, 12, tzinfo=UTC),
        health=20,
        food=20,
        inventory=inventory,
        equipment={},
        environment={"biome": "plains"},
    )


def _receipt(
    receipt_id: str,
    capability: str,
    before_hash: str,
    after_hash: str,
    *,
    previous_receipt_hash: str = "",
    session_id: str = "session-1",
    task_id: str = "task-1",
):
    started = datetime(2026, 7, 12, tzinfo=UTC)
    return ActionReceipt(
        receipt_id=receipt_id,
        session_id=session_id,
        task_id=task_id,
        correlation_id=f"corr-{receipt_id}",
        runtime_id="runtime-1",
        capability=capability,
        params={},
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        before_observation_hash=before_hash,
        after_observation_hash=after_hash,
        previous_receipt_hash=previous_receipt_hash,
        outcome=ActionOutcome.SUCCESS,
    )


def test_empty_inventory_frontier_contains_only_wood_collection() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()

    frontier = graph.frontier(tech.TechProgress(), _observation("obs-0", {}))

    assert [node.id for node in frontier] == ["wood_collection"]


def test_frontier_requires_all_prerequisites_even_if_inventory_has_item() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    observation = _observation("obs-0", {"iron_pickaxe": 1})

    frontier = graph.frontier(tech.TechProgress(), observation)

    assert "iron_pickaxe" not in {node.id for node in frontier}
    assert "wood_collection" in {node.id for node in frontier}


def test_verifier_rejects_postcondition_when_prerequisite_is_locked() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    before = _observation("obs-0", {"oak_log": 1})
    after = _observation("obs-1", {"oak_log": 1, "crafting_table": 1})
    receipt = _receipt("r-1", "craft", before.content_hash, after.content_hash)

    report = tech.TechEvidenceVerifier(graph).verify(
        node_id="crafting_table",
        progress=tech.TechProgress(),
        receipts=[receipt],
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert report.valid is False
    assert "MISSING_PREREQUISITE" in {failure.code for failure in report.failures}


def test_verifier_accepts_legitimate_wood_collection_evidence() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    before = _observation("obs-0", {})
    after = _observation("obs-1", {"oak_log": 1})
    receipt = _receipt("r-1", "collect", before.content_hash, after.content_hash)

    report = tech.TechEvidenceVerifier(graph).verify(
        node_id="wood_collection",
        progress=tech.TechProgress(),
        receipts=[receipt],
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert report.valid is True
    assert report.unlock_record is not None
    assert report.unlock_record.node_id == "wood_collection"
    assert report.unlock_record.receipt_hashes == (receipt.content_hash,)


def test_verifier_accepts_survival_mine_shaft_as_cobblestone_evidence() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    before = _observation("cobble-before", {"wooden_pickaxe": 1})
    after = _observation(
        "cobble-after",
        {"wooden_pickaxe": 1, "cobblestone": 12},
    )
    receipt = _receipt(
        "cobble-shaft",
        "mine_shaft",
        before.content_hash,
        after.content_hash,
    )
    progress = _progress("wood_collection", "crafting_table", "wooden_pickaxe")

    report = tech.TechEvidenceVerifier(graph).verify(
        node_id="cobblestone",
        progress=progress,
        receipts=[receipt],
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert graph.get("cobblestone").required_capabilities == ("mine_shaft",)
    assert report.valid is True
    assert report.unlock_record is not None


def test_verifier_rejects_item_injection_without_action_receipts() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    before = _observation("obs-0", {})
    after = _observation("obs-1", {"oak_log": 64})

    report = tech.TechEvidenceVerifier(graph).verify(
        node_id="wood_collection",
        progress=tech.TechProgress(),
        receipts=[],
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert report.valid is False
    codes = {failure.code for failure in report.failures}
    assert "EMPTY_RECEIPT_CHAIN" in codes
    assert "UNEXPLAINED_INVENTORY_DELTA" in codes


def test_verifier_rejects_cross_session_receipt() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    before = _observation("obs-0", {})
    after = _observation("obs-1", {"oak_log": 1})
    receipt = _receipt(
        "r-1",
        "collect",
        before.content_hash,
        after.content_hash,
        session_id="session-other",
    )

    report = tech.TechEvidenceVerifier(graph).verify(
        node_id="wood_collection",
        progress=tech.TechProgress(),
        receipts=[receipt],
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert report.valid is False
    assert "SESSION_MISMATCH" in {failure.code for failure in report.failures}


def test_verifier_rejects_broken_receipt_and_observation_links() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    before = _observation("obs-0", {})
    middle = _observation("obs-1", {})
    after = _observation("obs-2", {"oak_log": 1})
    first = _receipt("r-1", "goto", before.content_hash, middle.content_hash)
    second = _receipt(
        "r-2",
        "collect",
        "wrong-observation",
        after.content_hash,
        previous_receipt_hash="wrong-receipt",
    )

    report = tech.TechEvidenceVerifier(graph).verify(
        node_id="wood_collection",
        progress=tech.TechProgress(),
        receipts=[first, second],
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    codes = {failure.code for failure in report.failures}
    assert report.valid is False
    assert "BROKEN_RECEIPT_LINK" in codes
    assert "BROKEN_OBSERVATION_LINK" in codes


def _progress(*node_ids: str):
    tech = _tech()
    return tech.TechProgress(unlocked_nodes=frozenset(node_ids))


def test_initial_graph_defines_survival_path_through_iron_pickaxe() -> None:
    graph = _tech().build_survival_tech_graph()

    assert graph.get("crafting_table").prerequisites == {"wood_collection"}
    assert graph.get("wooden_pickaxe").prerequisites == {"crafting_table"}
    assert graph.get("cobblestone").prerequisites == {"wooden_pickaxe"}
    assert graph.get("stone_pickaxe").prerequisites == {"cobblestone", "crafting_table"}
    assert graph.get("furnace").prerequisites == {"cobblestone", "crafting_table"}
    assert graph.get("iron_ingot").prerequisites == {"stone_pickaxe", "furnace"}
    assert graph.get("iron_pickaxe").prerequisites == {"iron_ingot", "crafting_table"}
    assert graph.get("gold_ore").prerequisites == {"iron_pickaxe"}


def test_iron_ingot_task_allows_safe_descent_but_still_requires_collect_and_smelt() -> None:
    node = _tech().build_survival_tech_graph().get("iron_ingot")

    assert "mine_shaft" in node.allowed_capabilities
    assert node.required_capabilities == ("collect", "smelt")


def test_iron_ingot_task_allows_crafting_replacement_stone_pickaxe() -> None:
    node = _tech().build_survival_tech_graph().get("iron_ingot")

    assert "craft" in node.allowed_capabilities
    assert node.required_capabilities == ("collect", "smelt")


def test_cobblestone_task_allows_crafting_replacement_wooden_pickaxe() -> None:
    node = _tech().build_survival_tech_graph().get("cobblestone")

    assert "craft" in node.allowed_capabilities
    assert node.required_capabilities == ("mine_shaft",)


def test_scheduler_skips_cooled_node_when_alternative_frontier_exists() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    scheduler = tech.FrontierScheduler(graph, failure_cooldown=4)
    progress = _progress("wood_collection", "crafting_table", "wooden_pickaxe", "cobblestone")
    observation = _observation("obs-0", {"cobblestone": 16})
    for _ in range(4):
        scheduler.record_failure("stone_pickaxe")

    selection = scheduler.select(progress, observation)

    assert selection.kind == "technology"
    assert selection.node.id == "furnace"
    assert selection.discovery is None


def test_scheduler_returns_bounded_discovery_when_only_frontier_is_cooled() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    scheduler = tech.FrontierScheduler(graph, failure_cooldown=2)
    observation = _observation("obs-0", {})
    scheduler.record_failure("wood_collection")
    scheduler.record_failure("wood_collection")

    selection = scheduler.select(tech.TechProgress(), observation)

    assert selection.kind == "discovery"
    assert selection.node is None
    assert selection.discovery.blocked_node_id == "wood_collection"
    assert 0 < selection.discovery.radius <= 128
    assert 0 < selection.discovery.seconds <= 600


def test_scheduler_uses_underground_discovery_then_reopens_cobblestone_frontier() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    scheduler = tech.FrontierScheduler(graph, failure_cooldown=1)
    progress = _progress("wood_collection", "crafting_table", "wooden_pickaxe")
    observation = _observation("obs-underground", {"wooden_pickaxe": 1})
    scheduler.record_failure("cobblestone")

    discovery = scheduler.select(progress, observation)
    retry = scheduler.select(progress, observation)

    assert discovery.kind == "discovery"
    assert discovery.discovery.capability == "mine_shaft"
    assert discovery.discovery.params == {"target_y": 50}
    assert retry.kind == "technology"
    assert retry.node.id == "cobblestone"


def test_scheduler_uses_bounded_mid_depth_discovery_for_iron() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    scheduler = tech.FrontierScheduler(graph, failure_cooldown=1)
    progress = _progress(
        "wood_collection",
        "crafting_table",
        "wooden_pickaxe",
        "cobblestone",
        "stone_pickaxe",
        "furnace",
    )
    observation = _observation("obs-iron", {"stone_pickaxe": 1, "furnace": 1})
    scheduler.record_failure("iron_ingot")

    discovery = scheduler.select(progress, observation)

    assert discovery.kind == "discovery"
    assert discovery.discovery.capability == "mine_shaft"
    assert discovery.discovery.params == {"target_y": 40}


def test_scheduler_exposes_gold_frontier_after_committed_iron_pickaxe() -> None:
    tech = _tech()
    graph = tech.build_survival_tech_graph()
    scheduler = tech.FrontierScheduler(graph)
    progress = _progress(
        "wood_collection",
        "crafting_table",
        "wooden_pickaxe",
        "cobblestone",
        "stone_pickaxe",
        "furnace",
        "iron_ingot",
        "iron_pickaxe",
    )

    selection = scheduler.select(progress, _observation("obs-0", {"iron_pickaxe": 1}))

    assert selection.kind == "technology"
    assert selection.node.id == "gold_ore"
