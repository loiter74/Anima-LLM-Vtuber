from __future__ import annotations

from animetta.tools.minecraft.showcase.dialogue_regression import (
    DialogueCaseTrace,
    ToolCallTrace,
    evaluate_dialogue_catalog,
)


def _trace(case_id: str, **updates: object) -> DialogueCaseTrace:
    payload: dict[str, object] = {
        "case_id": case_id,
        "user_text": f"user input for {case_id}",
        "visible_response": "可见回复",
        "tool_calls": (),
        "gameplay_submission_count": 0,
    }
    payload.update(updates)
    return DialogueCaseTrace.model_validate(payload)


def _call(name: str, outcome_code: str) -> ToolCallTrace:
    return ToolCallTrace(tool_name=name, outcome_code=outcome_code)


def test_d1_d8_catalog_passes_only_with_declared_control_semantics() -> None:
    compound_assertions = {
        "three_monsters": True,
        "starter_shelter_exact": True,
        "bounded_autonomy": True,
        "novel_item_required": True,
        "trusted_skill_required": True,
        "two_vanilla_advancements_required": True,
        "exactly_one_mc_execute": True,
        "hidden_target_not_revealed": True,
    }
    traces = (
        _trace(
            "D1",
            tool_calls=(_call("mc_execute", "ADMITTED"),),
            gameplay_submission_count=1,
            semantic_assertions={"mission_branch": True},
        ),
        _trace(
            "D2",
            tool_calls=(_call("mc_execute", "ADMITTED"),),
            gameplay_submission_count=1,
            semantic_assertions=compound_assertions,
        ),
        _trace("D3"),
        _trace(
            "D4",
            tool_calls=(
                _call("mc_execute", "MC_MISSION_SCHEMA_INVALID"),
                _call("mc_execute", "ADMITTED"),
            ),
            gameplay_submission_count=1,
        ),
        _trace(
            "D5",
            tool_calls=(
                _call("mc_execute", "MC_MISSION_SCHEMA_INVALID"),
                _call("mc_execute", "MC_MISSION_REPAIR_EXHAUSTED"),
            ),
        ),
        _trace("D6", tool_calls=(_call("mc_status", "OK"),)),
        _trace("D7", tool_calls=(_call("mc_stop", "STOPPED"),)),
        _trace(
            "D8",
            committed_evidence=("combat:zombie", "advancement:story/root"),
            claimed_evidence=("combat:zombie",),
        ),
    )

    report = evaluate_dialogue_catalog(traces)

    assert report.passed is True
    assert tuple(item.case_id for item in report.cases) == (
        "D1",
        "D2",
        "D3",
        "D4",
        "D5",
        "D6",
        "D7",
        "D8",
    )


def test_catalog_rejects_post_stop_execution_and_uncommitted_narration() -> None:
    report = evaluate_dialogue_catalog(
        (
            _trace("D7", tool_calls=(_call("mc_stop", "STOPPED"), _call("mc_execute", "ADMITTED"))),
            _trace(
                "D8",
                committed_evidence=("combat:zombie",),
                claimed_evidence=("combat:zombie", "combat:dragon"),
            ),
        ),
        require_complete=False,
    )

    assert report.passed is False
    assert report.cases[0].reason_codes == ("POST_STOP_TOOL_CALL",)
    assert report.cases[1].reason_codes == ("UNCOMMITTED_EVIDENCE_CLAIM",)
