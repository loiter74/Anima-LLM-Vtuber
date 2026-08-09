"""Composite command budgets, reservations, and cumulative charging."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from animetta.tools.gamebot.contracts.v2 import BudgetVector


class BudgetExceededError(ValueError):
    """The parent command budget cannot cover requested work."""


class BudgetContractViolationError(ValueError):
    """Runtime usage exceeded the durable pre-dispatch reservation."""


class _BudgetModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class RequestedBudget(_BudgetModel):
    queue_timeout_ms: int | None = Field(default=None, gt=0)
    execution_timeout_ms: int | None = Field(default=None, gt=0)
    max_actions: int | None = Field(default=None, ge=0)
    max_strategy_attempts: int | None = Field(default=None, ge=0)
    max_travel_distance: float | None = Field(default=None, ge=0)
    max_blocks_changed: int | None = Field(default=None, ge=0)
    max_damage_taken: float | None = Field(default=None, ge=0)
    protected_items: frozenset[str] | None = None
    resource_consumption: dict[str, int] | None = None

    @field_validator("protected_items", mode="before")
    @classmethod
    def _normalize_json_protected_items(cls, items: object) -> object:
        if isinstance(items, list):
            return frozenset(items)
        return items


class ExecutionBudget(_BudgetModel):
    queue_timeout_ms: int = Field(gt=0)
    execution_timeout_ms: int = Field(gt=0)
    max_actions: int = Field(ge=0)
    max_strategy_attempts: int = Field(ge=0)
    max_travel_distance: float = Field(ge=0)
    max_blocks_changed: int = Field(ge=0)
    max_damage_taken: float = Field(ge=0)
    protected_items: frozenset[str] = frozenset()
    resource_consumption: dict[str, int] = Field(default_factory=dict)


class ModeBudgetPolicy(_BudgetModel):
    """Static maxima for every caller-selectable execution mode."""

    learn: ExecutionBudget
    live: ExecutionBudget
    fallback: ExecutionBudget
    atomic: ExecutionBudget

    def maximum_for(self, mode: str) -> ExecutionBudget:
        if mode not in {"learn", "live", "fallback", "atomic"}:
            raise KeyError(mode)
        return getattr(self, mode)


class BudgetUsage(_BudgetModel):
    max_actions: int = Field(default=0, ge=0)
    max_strategy_attempts: int = Field(default=0, ge=0)
    max_travel_distance: float = Field(default=0, ge=0)
    max_blocks_changed: int = Field(default=0, ge=0)
    max_damage_taken: float = Field(default=0, ge=0)
    resource_consumption: dict[str, int] = Field(default_factory=dict)

    def plus(self, other: BudgetUsage) -> BudgetUsage:
        resources = dict(self.resource_consumption)
        for name, amount in other.resource_consumption.items():
            resources[name] = resources.get(name, 0) + amount
        return BudgetUsage(
            max_actions=self.max_actions + other.max_actions,
            max_strategy_attempts=self.max_strategy_attempts + other.max_strategy_attempts,
            max_travel_distance=self.max_travel_distance + other.max_travel_distance,
            max_blocks_changed=self.max_blocks_changed + other.max_blocks_changed,
            max_damage_taken=self.max_damage_taken + other.max_damage_taken,
            resource_consumption=resources,
        )


def budget_usage_from_vector(vector: BudgetVector) -> BudgetUsage:
    """Project a runtime budget vector onto consumable mission usage."""

    return BudgetUsage(
        max_actions=vector.max_actions,
        max_strategy_attempts=vector.max_strategy_attempts,
        max_travel_distance=vector.max_travel_distance,
        max_blocks_changed=vector.max_blocks_changed,
        max_damage_taken=vector.max_damage_taken,
        resource_consumption=vector.resource_consumption,
    )


def effective_budget(
    requested: RequestedBudget | None, maximum: ExecutionBudget
) -> ExecutionBudget:
    request = requested or RequestedBudget()

    def clamp(name: str) -> int | float:
        wanted = getattr(request, name)
        allowed = getattr(maximum, name)
        return allowed if wanted is None else min(wanted, allowed)

    resources = {
        name: min((request.resource_consumption or {}).get(name, limit), limit)
        for name, limit in maximum.resource_consumption.items()
    }
    protected = maximum.protected_items | (request.protected_items or frozenset())
    return ExecutionBudget(
        queue_timeout_ms=int(clamp("queue_timeout_ms")),
        execution_timeout_ms=int(clamp("execution_timeout_ms")),
        max_actions=int(clamp("max_actions")),
        max_strategy_attempts=int(clamp("max_strategy_attempts")),
        max_travel_distance=float(clamp("max_travel_distance")),
        max_blocks_changed=int(clamp("max_blocks_changed")),
        max_damage_taken=float(clamp("max_damage_taken")),
        protected_items=protected,
        resource_consumption=resources,
    )


class BudgetAccount(_BudgetModel):
    limit: ExecutionBudget
    used: BudgetUsage = BudgetUsage()
    reservations: dict[str, BudgetUsage] = Field(default_factory=dict)

    @property
    def reserved(self) -> BudgetUsage:
        total = BudgetUsage()
        for reservation in self.reservations.values():
            total = total.plus(reservation)
        return total

    @property
    def remaining(self) -> ExecutionBudget:
        charged = self.used.plus(self.reserved)
        return ExecutionBudget(
            queue_timeout_ms=self.limit.queue_timeout_ms,
            execution_timeout_ms=self.limit.execution_timeout_ms,
            max_actions=self.limit.max_actions - charged.max_actions,
            max_strategy_attempts=(
                self.limit.max_strategy_attempts - charged.max_strategy_attempts
            ),
            max_travel_distance=(self.limit.max_travel_distance - charged.max_travel_distance),
            max_blocks_changed=(self.limit.max_blocks_changed - charged.max_blocks_changed),
            max_damage_taken=self.limit.max_damage_taken - charged.max_damage_taken,
            protected_items=self.limit.protected_items,
            resource_consumption={
                name: limit - charged.resource_consumption.get(name, 0)
                for name, limit in self.limit.resource_consumption.items()
            },
        )

    def _ensure_fits(self, usage: BudgetUsage, available: ExecutionBudget) -> None:
        fields = (
            "max_actions",
            "max_strategy_attempts",
            "max_travel_distance",
            "max_blocks_changed",
            "max_damage_taken",
        )
        if any(getattr(usage, name) > getattr(available, name) for name in fields):
            raise BudgetExceededError("BUDGET_EXHAUSTED")
        for name, amount in usage.resource_consumption.items():
            if amount > available.resource_consumption.get(name, 0):
                raise BudgetExceededError(f"BUDGET_EXHAUSTED: {name}")

    def charge(self, usage: BudgetUsage) -> Self:
        self._ensure_fits(usage, self.remaining)
        return self.model_copy(update={"used": self.used.plus(usage)}, deep=True)

    def reserve(self, reservation_id: str, maximum: BudgetUsage) -> Self:
        if reservation_id in self.reservations:
            raise ValueError(f"duplicate reservation: {reservation_id}")
        self._ensure_fits(maximum, self.remaining)
        reservations = dict(self.reservations)
        reservations[reservation_id] = maximum
        return self.model_copy(update={"reservations": reservations}, deep=True)

    def settle(self, reservation_id: str, actual: BudgetUsage) -> Self:
        reserved = self.reservations.get(reservation_id)
        if reserved is None:
            raise KeyError(reservation_id)
        try:
            self._ensure_fits(
                actual,
                ExecutionBudget(
                    queue_timeout_ms=self.limit.queue_timeout_ms,
                    execution_timeout_ms=self.limit.execution_timeout_ms,
                    protected_items=self.limit.protected_items,
                    **reserved.model_dump(mode="python"),
                ),
            )
        except BudgetExceededError as exc:
            raise BudgetContractViolationError("usage exceeds reservation") from exc
        reservations = dict(self.reservations)
        del reservations[reservation_id]
        return self.model_copy(
            update={"used": self.used.plus(actual), "reservations": reservations},
            deep=True,
        )
