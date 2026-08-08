"""Runtime observations and receipts become durable world facts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from animetta.tools.gamebot.contracts.v2 import ActionReceipt, Observation
from animetta.tools.minecraft.discovery.runtime import RuntimeDiscoveryProjector
from animetta.tools.minecraft.discovery.store import InMemoryWorldFactStore
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint
from animetta.tools.minecraft.voyager.goal_models import GoalSpec

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]


def _acquire_goal():
    return TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "acquire",
            "target": "raw_copper",
            "constraints": {"source_block": "copper_ore"},
            "success_predicates": [
                {
                    "kind": "inventory_at_least",
                    "item": "raw_copper",
                    "quantity": 1,
                }
            ],
        }
    )


async def test_acquire_goal_projects_visible_fact_and_committed_inventory_delta() -> None:
    store = InMemoryWorldFactStore()
    await store.connect()
    initial = Observation.model_validate(MESSAGES["Observation"])
    final_payload = initial.model_dump(mode="json")
    final_payload.update(
        {
            "observation_id": "observation-copper-after",
            "content_hash": "c" * 64,
            "captured_at_ms": initial.captured_at_ms + 100,
            "tick": initial.tick + 1,
            "action_sequence": initial.action_sequence + 1,
            "inventory": {**initial.inventory, "raw_copper": 1},
            "visible_blocks": [
                {
                    "block_id": "minecraft:copper_ore",
                    "position": {"x": 20, "y": 63, "z": 20},
                }
            ],
        }
    )
    final = Observation.model_validate(final_payload)
    receipt_payload = dict(MESSAGES["ActionReceipt"])
    receipt_payload.update(
        {
            "receipt_id": "receipt-copper",
            "command_id": "mission-copper",
            "correlation_id": "correlation-copper",
            "runtime_instance_id": final.runtime_instance_id,
            "before_observation_hash": initial.content_hash,
            "after_observation_hash": final.content_hash,
            "explained_mutations": [
                {
                    "kind": "block",
                    "subject": "block:minecraft:overworld:20:63:20",
                    "delta": -1,
                    "details": {"block_type": "minecraft:copper_ore"},
                },
                {
                    "kind": "inventory",
                    "subject": "raw_copper",
                    "delta": 1,
                    "details": {"before": 0, "after": 1},
                },
            ],
            "content_hash": "d" * 64,
        }
    )
    receipt = ActionReceipt.model_validate(receipt_payload)
    projector = RuntimeDiscoveryProjector(store=store)

    result = await projector.project_goal(
        goal=_acquire_goal(),
        command_id="mission-copper",
        initial=initial,
        final=final,
        receipts=(receipt,),
        fallback_only=False,
    )

    assert {fact.identity.fact_key for fact in result.observed} >= {
        "minecraft:copper_ore",
        "minecraft:raw_copper",
    }
    assert tuple(fact.identity.fact_key for fact in result.acquired) == ("minecraft:raw_copper",)
    assert result.acquired[0].acquisition_receipt_ref == "receipt:receipt-copper"
    scoped = await store.list_scope(
        world_identity_hash=final.profile.world_identity_hash,
        environment_fingerprint=stable_environment_fingerprint(final.profile),
    )
    assert any(fact.state == "acquired" for fact in scoped)
