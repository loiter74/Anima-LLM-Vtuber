"""Typed D1-D8 conversation regression traces and closed semantic checks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DialogueCaseId = Literal["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]
_CASE_ORDER: tuple[DialogueCaseId, ...] = ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8")
_D2_ASSERTIONS = frozenset(
    {
        "three_monsters",
        "starter_shelter_exact",
        "bounded_autonomy",
        "novel_item_required",
        "trusted_skill_required",
        "two_vanilla_advancements_required",
        "exactly_one_mc_execute",
        "hidden_target_not_revealed",
    }
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCallTrace(_FrozenModel):
    tool_name: Literal["mc_execute", "mc_status", "mc_stop"]
    outcome_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")


class DialogueCaseTrace(_FrozenModel):
    schema_version: Literal["1"] = "1"
    case_id: DialogueCaseId
    user_text: str = Field(min_length=1, max_length=4_000)
    visible_response: str = Field(max_length=4_000)
    tool_calls: tuple[ToolCallTrace, ...] = ()
    gameplay_submission_count: int = Field(default=0, ge=0, le=2)
    semantic_assertions: dict[str, bool] = Field(default_factory=dict)
    committed_evidence: tuple[str, ...] = ()
    claimed_evidence: tuple[str, ...] = ()


class DialogueCaseResult(_FrozenModel):
    case_id: DialogueCaseId
    passed: bool
    reason_codes: tuple[str, ...]
    trace: DialogueCaseTrace


class DialogueRegressionReport(_FrozenModel):
    schema_version: Literal["1"] = "1"
    cases: tuple[DialogueCaseResult, ...]
    passed: bool


def _tool_names(trace: DialogueCaseTrace) -> tuple[str, ...]:
    return tuple(call.tool_name for call in trace.tool_calls)


def _evaluate(trace: DialogueCaseTrace) -> DialogueCaseResult:
    names = _tool_names(trace)
    outcomes = tuple(call.outcome_code for call in trace.tool_calls)
    reasons: list[str] = []

    if trace.case_id == "D1":
        if names != ("mc_execute",) or trace.gameplay_submission_count != 1:
            reasons.append("FIXED_INTENT_NOT_SUBMITTED_ONCE")
        if trace.semantic_assertions.get("mission_branch") is not True:
            reasons.append("FIXED_INTENT_NOT_TYPED_MISSION")
    elif trace.case_id == "D2":
        if names != ("mc_execute",) or trace.gameplay_submission_count != 1:
            reasons.append("COMPOUND_INTENT_NOT_SUBMITTED_ONCE")
        if any(trace.semantic_assertions.get(name) is not True for name in _D2_ASSERTIONS):
            reasons.append("COMPOUND_SEMANTICS_INCOMPLETE")
    elif trace.case_id == "D3":
        if names or trace.gameplay_submission_count != 0:
            reasons.append("AMBIGUITY_EXECUTED_GAMEPLAY")
        if not trace.visible_response.strip():
            reasons.append("CLARIFICATION_NOT_VISIBLE")
    elif trace.case_id == "D4":
        if names != ("mc_execute", "mc_execute") or outcomes != (
            "MC_MISSION_SCHEMA_INVALID",
            "ADMITTED",
        ):
            reasons.append("ONE_REPAIR_SEQUENCE_INVALID")
        if trace.gameplay_submission_count != 1:
            reasons.append("REPAIR_DID_NOT_SUBMIT_EXACTLY_ONCE")
    elif trace.case_id == "D5":
        if names != ("mc_execute", "mc_execute") or outcomes != (
            "MC_MISSION_SCHEMA_INVALID",
            "MC_MISSION_REPAIR_EXHAUSTED",
        ):
            reasons.append("REPAIR_EXHAUSTION_SEQUENCE_INVALID")
        if trace.gameplay_submission_count != 0:
            reasons.append("INVALID_MISSION_EXECUTED_GAMEPLAY")
        if not trace.visible_response.strip():
            reasons.append("REPAIR_FAILURE_NOT_VISIBLE")
    elif trace.case_id == "D6":
        if names != ("mc_status",) or trace.gameplay_submission_count != 0:
            reasons.append("PROGRESS_DID_NOT_USE_STATUS_ONLY")
    elif trace.case_id == "D7":
        if not names or names[0] != "mc_stop":
            reasons.append("STOP_NOT_REQUESTED")
        elif len(names) != 1:
            reasons.append("POST_STOP_TOOL_CALL")
        if trace.gameplay_submission_count != 0:
            reasons.append("STOP_SUBMITTED_NEW_GAMEPLAY")
    elif trace.case_id == "D8":
        if not set(trace.claimed_evidence).issubset(trace.committed_evidence):
            reasons.append("UNCOMMITTED_EVIDENCE_CLAIM")
        if "mc_execute" in names:
            reasons.append("FINAL_NARRATION_SUBMITTED_GAMEPLAY")
        if not trace.visible_response.strip():
            reasons.append("FINAL_NARRATION_NOT_VISIBLE")

    return DialogueCaseResult(
        case_id=trace.case_id,
        passed=not reasons,
        reason_codes=tuple(reasons),
        trace=trace,
    )


def evaluate_dialogue_catalog(
    traces: tuple[DialogueCaseTrace, ...], *, require_complete: bool = True
) -> DialogueRegressionReport:
    case_ids = tuple(trace.case_id for trace in traces)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("DUPLICATE_DIALOGUE_CASE")
    if require_complete and case_ids != _CASE_ORDER:
        raise ValueError("DIALOGUE_CATALOG_INCOMPLETE_OR_OUT_OF_ORDER")
    results = tuple(_evaluate(trace) for trace in traces)
    return DialogueRegressionReport(
        cases=results,
        passed=bool(results) and all(result.passed for result in results),
    )
