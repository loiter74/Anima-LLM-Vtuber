from __future__ import annotations

from animetta.tools.minecraft.mission.adaptive import (
    AdaptiveMissionPolicy,
    AdaptiveMissionState,
    ExplorationFrontier,
)


def _state(**updates: object) -> AdaptiveMissionState:
    payload: dict[str, object] = {
        "mission_id": "showcase-001",
        "observation_ref": "observation:obs-001",
        "observed_fact_keys": frozenset(),
        "acquired_fact_ids": frozenset(),
        "trusted_revision_hashes": frozenset(),
        "inventory": {},
        "completed_adaptive_phases": frozenset(),
    }
    payload.update(updates)
    return AdaptiveMissionState.model_validate(payload)


def test_policy_derives_explore_learn_validate_and_reuse_from_committed_state() -> None:
    policy = AdaptiveMissionPolicy(
        frontier=ExplorationFrontier(
            x=20,
            y=63,
            z=20,
            target_block="minecraft:copper_ore",
            target_item="minecraft:raw_copper",
        )
    )

    explore = policy.decide(_state())
    learn = policy.decide(
        _state(
            observation_ref="observation:obs-copper",
            observed_fact_keys=frozenset({"block:minecraft:copper_ore"}),
            completed_adaptive_phases=frozenset({"explore"}),
        )
    )
    reuse = policy.decide(
        _state(
            observation_ref="observation:obs-validated",
            observed_fact_keys=frozenset({"block:minecraft:copper_ore"}),
            acquired_fact_ids=frozenset({"fact-raw-copper"}),
            trusted_revision_hashes=frozenset({"a" * 64}),
            inventory={"minecraft:raw_copper": 2},
            completed_adaptive_phases=frozenset({"explore", "learn_validate"}),
        )
    )
    verify = policy.decide(
        _state(
            observation_ref="observation:obs-reused",
            observed_fact_keys=frozenset({"block:minecraft:copper_ore"}),
            acquired_fact_ids=frozenset({"fact-raw-copper"}),
            trusted_revision_hashes=frozenset({"a" * 64}),
            inventory={"minecraft:raw_copper": 3},
            completed_adaptive_phases=frozenset({"explore", "learn_validate", "reuse"}),
        )
    )

    assert explore.exploration is not None
    assert explore.exploration.unvisited_frontier[0].goal.intent == "travel"
    assert learn.exploration is not None
    assert learn.exploration.new_facts[0].goal.constraints["adaptive_phase"] == ("learn_validate")
    assert reuse.exploration is not None
    reuse_goal = reuse.exploration.skill_gaps[0].goal
    assert reuse_goal.intent == "acquire"
    assert reuse_goal.quantity == 3
    assert reuse_goal.constraints["adaptive_phase"] == "reuse"
    assert verify.ready_for_verification is True
    assert verify.exploration is None


def test_policy_stops_when_exploration_frontier_yields_no_target_fact() -> None:
    policy = AdaptiveMissionPolicy(
        frontier=ExplorationFrontier(
            x=20,
            y=63,
            z=20,
            target_block="minecraft:copper_ore",
            target_item="minecraft:raw_copper",
        )
    )

    decision = policy.decide(_state(completed_adaptive_phases=frozenset({"explore"})))

    assert decision.exploration is None
    assert decision.stop_reason == "NOVELTY_EXHAUSTED"
