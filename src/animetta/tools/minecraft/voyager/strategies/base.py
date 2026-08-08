"""Typed strategy protocol; strategies never perform runtime I/O."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import Observation

from ..budget import BudgetUsage
from ..goal_models import GoalSpec


class _Decision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ExecuteStep(_Decision):
    kind: str = "execute"
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parameters: dict[str, Any]
    maximum_cost: BudgetUsage


class Complete(_Decision):
    kind: str = "complete"
    output: dict[str, Any] = Field(default_factory=dict)


class StrategyFailure(_Decision):
    kind: str = "failure"
    code: str
    message: str


StrategyDecision = ExecuteStep | Complete | StrategyFailure


class BoundedStrategy(Protocol):
    def prepare(self, goal: GoalSpec | None) -> dict[str, Any]: ...

    def propose(
        self,
        state: dict[str, Any],
        observation: Observation,
    ) -> StrategyDecision: ...

    def accept_result(self, state: dict[str, Any], result: object) -> dict[str, Any]: ...
