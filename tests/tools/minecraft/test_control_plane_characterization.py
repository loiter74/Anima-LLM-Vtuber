"""Pre-cutover behavior snapshots for Minecraft domain ownership migration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from animetta.tools.gamebot.contracts import (
    ActionReceipt,
    CapabilityManifest,
    GameBotObservation,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import Skill, SkillTrustStage
from animetta.tools.minecraft.survival.models import PHASE_ORDER, SurvivalPhase
from animetta.tools.minecraft.tech_tree.graph import (
    FrontierScheduler,
    TechProgress,
    build_survival_tech_graph,
)


def _observation() -> GameBotObservation:
    return GameBotObservation(
        observation_id="obs-frontier",
        correlation_id="corr-frontier",
        runtime_id="runtime-characterization",
        captured_at=datetime(2026, 8, 1, tzinfo=UTC),
        inventory={},
    )


def test_survival_graph_and_frontier_order_are_characterized() -> None:
    graph = build_survival_tech_graph()
    progress = TechProgress()
    scheduler = FrontierScheduler(graph, failure_cooldown=2)

    assert list(graph._nodes) == [
        "wood_collection",
        "crafting_table",
        "wooden_pickaxe",
        "cobblestone",
        "stone_pickaxe",
        "furnace",
        "iron_ingot",
        "iron_pickaxe",
        "gold_ore",
    ]
    first = scheduler.select(progress, _observation())
    assert first.kind == "technology"
    assert first.node is not None and first.node.id == "wood_collection"

    scheduler.record_failure("wood_collection")
    scheduler.record_failure("wood_collection")
    discovery = scheduler.select(progress, _observation())
    assert discovery.kind == "discovery"
    assert discovery.discovery is not None
    assert discovery.discovery.blocked_node_id == "wood_collection"


def test_deterministic_survival_phase_order_is_characterized() -> None:
    assert PHASE_ORDER == [
        SurvivalPhase.WOOD,
        SurvivalPhase.CRAFTING_TABLE,
        SurvivalPhase.WOODEN_PICKAXE,
        SurvivalPhase.COBBLESTONE,
        SurvivalPhase.STONE_KIT,
        SurvivalPhase.FUEL,
        SurvivalPhase.IRON_ORE,
        SurvivalPhase.SMELT_IRON,
        SurvivalPhase.IRON_GEAR,
        SurvivalPhase.DONE,
    ]


async def test_legacy_skill_sqlite_row_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-skills.db"
    library = SkillLibrary(db_path=str(db_path))
    await library.init_db()
    await library.save_skill(
        Skill(
            id="legacy-code-skill",
            name="Legacy code skill",
            description="migration source",
            body={"code": "await collect('oak_log', 1)"},
            is_learned=True,
            validated=True,
            trust_stage=SkillTrustStage.CANDIDATE,
        )
    )
    await library.close_db()

    reloaded = SkillLibrary(db_path=str(db_path))
    await reloaded.init_db()
    try:
        skill = await reloaded.get_skill("legacy-code-skill")
        assert skill is not None
        assert skill.body == {"code": "await collect('oak_log', 1)"}
        assert skill.validated is True
    finally:
        await reloaded.close_db()


def test_external_runtime_v1_fixture_shape_is_characterized() -> None:
    fixture_path = Path(__file__).with_name("fixtures") / "gamebot_v1_characterization.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    manifest = CapabilityManifest.model_validate(payload["manifest"])
    observation = GameBotObservation.model_validate(payload["observation"])
    receipt = ActionReceipt.model_validate(payload["receipt"])

    assert manifest.runtime_id == observation.runtime_id == receipt.runtime_id
    assert manifest.capability(receipt.capability).risk.value == "survival_safe"
    assert receipt.params == {"block_type": "oak_log", "count": 1}
