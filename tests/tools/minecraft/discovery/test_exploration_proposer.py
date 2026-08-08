from __future__ import annotations

from importlib import import_module

from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import DiscoverGoal, WorldFactObserved


def _module():
    return import_module("animetta.tools.minecraft.discovery.exploration")


def _seed(exploration, source: str, target: str, value: float):
    return exploration.ExplorationSeed(
        source=source,
        signal_id=f"signal-{source.replace('_', '-')}",
        goal=DiscoverGoal(
            intent="discover",
            target=target,
            discovery_kind="item",
            success_predicates=(
                WorldFactObserved(
                    kind="world_fact_observed",
                    fact_kind="item",
                    fact_key=target,
                ),
            ),
        ),
        evidence_refs=(f"evidence:{source}",),
        conservative_cost=BudgetUsage(max_actions=1),
        expected_value=value,
    )


def _inputs(exploration, **updates: object):
    payload: dict[str, object] = {
        "mission_id": "showcase-001",
        "observation_ref": "observation:obs-001",
        "observation_committed": True,
        "mission_gaps": (_seed(exploration, "mission_gap", "minecraft:oak_log", 0.95),),
        "technology_frontier": (
            _seed(
                exploration,
                "technology_frontier",
                "minecraft:crafting_table",
                0.85,
            ),
        ),
        "new_facts": (_seed(exploration, "new_fact", "minecraft:copper_ingot", 0.75),),
        "unvisited_frontier": (_seed(exploration, "unvisited_frontier", "minecraft:desert", 0.65),),
        "recovery_prerequisites": (
            _seed(
                exploration,
                "recovery_prerequisite",
                "minecraft:cooked_beef",
                0.55,
            ),
        ),
    }
    payload.update(updates)
    return exploration.ExplorationInput.model_validate(payload)


def test_generates_candidates_from_all_closed_frontier_sources() -> None:
    exploration = _module()

    result = exploration.ExplorationProposer(
        exploration.ExplorationBounds(max_candidates=5, min_expected_value=0.5)
    ).propose(_inputs(exploration))

    assert result.outcome == "CANDIDATES_READY"
    assert [candidate.rationale_code for candidate in result.candidates] == [
        "MISSION_GAP",
        "TECHNOLOGY_FRONTIER",
        "DISCOVERY_GAP",
        "UNVISITED_FRONTIER",
        "RECOVERY_PREREQUISITE",
    ]
    assert result.proposal == result.candidates[0]
    assert result.proposal.origin == "curriculum"
    assert result.candidates[-1].origin == "recovery"
    assert all(
        candidate.evidence_refs[0] == "observation:obs-001" for candidate in result.candidates
    )


def test_candidate_count_value_and_duplicate_bounds_are_deterministic() -> None:
    exploration = _module()
    inputs = _inputs(exploration)
    duplicate_hash = inputs.mission_gaps[0].goal.canonical_hash

    result = exploration.ExplorationProposer(
        exploration.ExplorationBounds(max_candidates=2, min_expected_value=0.7)
    ).propose(inputs.model_copy(update={"proposed_goal_hashes": frozenset({duplicate_hash})}))

    assert [candidate.expected_value for candidate in result.candidates] == [0.85, 0.75]
    assert result.rejected_counts == {
        "duplicate": 1,
        "below_value": 2,
        "over_count": 0,
    }


def test_one_committed_observation_can_issue_only_one_child_proposal() -> None:
    exploration = _module()
    proposer = exploration.ExplorationProposer(
        exploration.ExplorationBounds(max_candidates=5, min_expected_value=0.5)
    )

    first = proposer.propose(_inputs(exploration))
    repeated = proposer.propose(
        _inputs(
            exploration,
            consumed_observation_refs=frozenset({"observation:obs-001"}),
        )
    )
    uncommitted = proposer.propose(
        _inputs(
            exploration,
            observation_ref="observation:obs-002",
            observation_committed=False,
        )
    )

    assert first.proposal is not None
    assert len(first.candidates) == 5
    assert repeated.outcome == "OBSERVATION_ALREADY_CONSUMED"
    assert repeated.proposal is None
    assert uncommitted.outcome == "WAITING_COMMITTED_OBSERVATION"
    assert uncommitted.proposal is None


def test_skill_gap_candidate_keeps_skill_policy_attribution() -> None:
    exploration = _module()
    inputs = exploration.ExplorationInput(
        mission_id="showcase-001",
        observation_ref="observation:obs-reuse",
        observation_committed=True,
        skill_gaps=(_seed(exploration, "skill_gap", "minecraft:raw_copper", 0.9),),
    )

    result = exploration.ExplorationProposer(
        exploration.ExplorationBounds(max_candidates=1, min_expected_value=0.5)
    ).propose(inputs)

    assert result.proposal is not None
    assert result.proposal.rationale_code == "SKILL_GAP"


def test_all_filtered_candidates_end_with_structured_novelty_exhaustion() -> None:
    exploration = _module()
    inputs = _inputs(exploration)

    result = exploration.ExplorationProposer(
        exploration.ExplorationBounds(max_candidates=5, min_expected_value=1.0)
    ).propose(inputs)

    assert result.outcome == "NOVELTY_EXHAUSTED"
    assert result.candidates == ()
    assert result.proposal is None
