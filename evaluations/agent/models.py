"""Versioned trajectory and deterministic budget contracts."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TrajectoryStepKind = Literal["node", "tool", "approval", "error", "terminal"]


class TrajectoryStepV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TrajectoryStepKind
    name: str
    status: str
    argument_digest: str | None = None
    retry_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    error_code: str | None = None
    approval_result: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_usage: bool = False
    usage_recorded: bool = False
    cost_usd: float = Field(default=0, ge=0)
    policy_decision: Literal["allow", "deny", "approval_required"] | None = None
    parameters_valid: bool | None = None
    request_id: str | None = None
    recovered: bool = False
    tool_effect: Literal["read_only", "state_changing", "unknown"] | None = None


class AgentTrajectoryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    trace_id: str
    runtime_profile: str
    steps: tuple[TrajectoryStepV1, ...]
    terminal_status: str
    duration_ms: float = Field(default=0, ge=0)
    raw_content_saved: Literal[False] = False

    @property
    def total_cost_usd(self) -> float:
        return sum(step.cost_usd for step in self.steps)

    @property
    def total_input_tokens(self) -> int:
        return sum(step.input_tokens for step in self.steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(step.output_tokens for step in self.steps)

    @property
    def tool_calls(self) -> tuple[TrajectoryStepV1, ...]:
        return tuple(step for step in self.steps if step.kind == "tool")

    @property
    def has_duplicate_tool_call(self) -> bool:
        identities = [(step.name, step.argument_digest) for step in self.tool_calls]
        return any(count > 1 for count in Counter(identities).values())


class ModelBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = 6000
    output_tokens: int = 4096
    tool_calls: int = 5
    cost_usd: float = 0.005
    llm_calls: int = 1


class EvaluationFindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class EvaluationResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    findings: tuple[EvaluationFindingV1, ...]
    authoritative: bool = True


def trajectory_from_ledger(detail: dict[str, Any]) -> AgentTrajectoryV1:
    steps: list[TrajectoryStepV1] = []
    operations = list(detail.get("operations", []))
    operations.sort(key=lambda item: float(item.get("started_at") or 0))
    for operation in operations:
        attributes = operation.get("attributes") or {}
        name = str(operation.get("name") or "unknown")
        is_tool = name.startswith("tool:")
        is_approval = name.startswith("approval:")
        is_policy = name.startswith("tool_policy:")
        kind: TrajectoryStepKind = (
            "tool" if is_tool else "approval" if is_approval else "error" if is_policy else "node"
        )
        steps.append(
            TrajectoryStepV1(
                kind=kind,
                name=(
                    name.removeprefix("tool:")
                    .removeprefix("approval:")
                    .removeprefix("tool_policy:")
                ),
                status=str(operation.get("status") or "pending"),
                argument_digest=_optional_string(attributes.get("arguments_digest")),
                retry_count=max(0, int(attributes.get("retry_count") or 0)),
                latency_ms=max(0.0, float(operation.get("duration_ms") or 0)),
                error_code=_optional_string(operation.get("error_type")),
                approval_result=_optional_string(attributes.get("approval_result")),
                input_tokens=max(0, int(attributes.get("usage_input_tokens") or 0)),
                cached_input_tokens=max(0, int(attributes.get("usage_cached_input_tokens") or 0)),
                output_tokens=max(0, int(attributes.get("usage_output_tokens") or 0)),
                estimated_usage=attributes.get("usage_estimated") is True,
                usage_recorded="usage_schema_version" in attributes,
                cost_usd=max(0.0, float(attributes.get("usage_total_cost_usd") or 0)),
                policy_decision=("deny" if is_policy else None),
                request_id=_optional_string(attributes.get("minecraft_request_id")),
                tool_effect=attributes.get("tool_effect"),
            )
        )
    outcome = str(detail.get("outcome") or "unknown")
    steps.append(TrajectoryStepV1(kind="terminal", name="turn", status=outcome))
    return AgentTrajectoryV1(
        trace_id=str(detail.get("trace_id") or "unknown"),
        runtime_profile=str(detail.get("runtime_profile") or "unknown"),
        steps=tuple(steps),
        terminal_status=outcome,
        duration_ms=max(0.0, float(detail.get("duration_ms") or 0)),
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value not in {None, ""} else None
