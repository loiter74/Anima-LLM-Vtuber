from __future__ import annotations

from types import SimpleNamespace

from animetta.tools.minecraft.core.tools import MinecraftExecuteToolInput
from animetta.tools.minecraft.mission.schema import build_golden_fixture
from animetta.tools.minecraft.showcase.live import (
    _added_advancement_ids,
    _mission_advancement_events,
    _normalize_model_execute_args,
)
from scripts.minecraft_real_model_contract import (
    _collect_independent_calls,
    _starter_shelter_budget_admissible,
    _starter_shelter_static_cost,
)


async def test_real_model_gate_uses_three_fresh_independent_conversations() -> None:
    history_lengths: list[int] = []

    async def invoke(user_text, history):
        assert user_text
        history_lengths.append(len(history))
        return {"content": "ok", "tool_calls": []}

    def validate(_response):
        return {"valid": True, "semantic_assertions": {"all": True}}, None

    calls = await _collect_independent_calls(
        invoke=invoke,
        validate=validate,
        independent_calls=3,
    )

    assert len(calls) == 3
    assert history_lengths == [0, 0, 0]
    assert all(call["final_validation"]["valid"] for call in calls)


def test_real_model_gate_rejects_shelter_budget_below_compiled_cost() -> None:
    static_cost = _starter_shelter_static_cost()
    assert static_cost.max_actions == 83
    assert static_cost.max_blocks_changed == 85

    insufficient = SimpleNamespace(
        objectives=(
            SimpleNamespace(
                goal=SimpleNamespace(
                    success_predicates=(
                        SimpleNamespace(
                            blueprint_id="starter-shelter-v1",
                        ),
                    ),
                ),
                budget=SimpleNamespace(max_actions=80, max_blocks_changed=80),
            ),
        ),
    )
    admissible = SimpleNamespace(
        objectives=(
            SimpleNamespace(
                goal=SimpleNamespace(
                    success_predicates=(
                        SimpleNamespace(
                            blueprint_id="starter-shelter-v1",
                        ),
                    ),
                ),
                budget=SimpleNamespace(max_actions=84, max_blocks_changed=85),
            ),
        ),
    )

    assert _starter_shelter_budget_admissible(insufficient) is False
    assert _starter_shelter_budget_admissible(admissible) is True


def test_real_model_gate_recovers_unambiguous_missing_mission_discriminator() -> None:
    args = {
        "request_id": "survival-showcase-v1",
        "mission": build_golden_fixture()["mission_spec"],
    }

    normalized = _normalize_model_execute_args(args)
    validated = MinecraftExecuteToolInput.model_validate(normalized)

    assert normalized is not args
    assert normalized["kind"] == "mission"
    assert validated.request.kind == "mission"


def test_real_model_gate_does_not_rewrite_ambiguous_or_atomic_input() -> None:
    mission = build_golden_fixture()["mission_spec"]

    ambiguous = {"request_id": "ambiguous-v1", "mission": mission, "action": {}}
    atomic = {"request_id": "atomic-v1", "action": {"kind": "observe"}}

    assert _normalize_model_execute_args(ambiguous) == ambiguous
    assert _normalize_model_execute_args(atomic) == atomic


def test_final_evidence_projects_added_vanilla_advancements() -> None:
    events = (
        SimpleNamespace(action="add", advancement_id="minecraft:adventure/root"),
        SimpleNamespace(action="remove", advancement_id="minecraft:story/root"),
        SimpleNamespace(action="add", advancement_id="minecraft:adventure/kill_a_mob"),
    )

    assert _added_advancement_ids(events) == [
        "minecraft:adventure/root",
        "minecraft:adventure/kill_a_mob",
    ]


async def test_final_evidence_uses_successful_mission_command_when_last_command_failed() -> None:
    first = SimpleNamespace(
        content_hash="event-1",
        observed_at_ms=1,
        action="add",
        advancement_id="minecraft:adventure/adventuring_time",
    )
    second = SimpleNamespace(
        content_hash="event-2",
        observed_at_ms=2,
        action="add",
        advancement_id="minecraft:adventure/kill_all_mobs",
    )

    class Collector:
        async def current_advancement_events(self, command_id):
            if command_id == "failed-build":
                return ()
            return (first, second)

    events = await _mission_advancement_events(
        Collector(),
        ("successful-combat", "failed-build"),
    )

    assert events == (first, second)
