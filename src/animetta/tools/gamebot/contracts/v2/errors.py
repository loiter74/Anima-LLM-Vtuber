"""Structured GameBot v2 errors."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import V2ContractModel


class RuntimeProtocolError(V2ContractModel):
    """Machine-readable failure semantics used for control decisions."""

    schema_version: Literal["2"] = "2"
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    message: str = Field(max_length=1000)
    phase: Literal[
        "request",
        "admission",
        "policy",
        "budget",
        "runtime",
        "verification",
        "recovery",
        "internal",
    ]
    command_id: str | None = None
    step_id: str | None = None
    correlation_id: str | None = None
    outcome_known: bool
    world_may_have_changed: bool
    caller_may_resubmit: bool
    operator_action: str = Field(min_length=1, max_length=500)
    details: dict[str, object] = Field(default_factory=dict)
