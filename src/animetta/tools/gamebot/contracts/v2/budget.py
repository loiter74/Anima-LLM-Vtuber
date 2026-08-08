"""Composite runtime budget values."""

from __future__ import annotations

from pydantic import Field

from ._base import V2ContractModel


class BudgetVector(V2ContractModel):
    """Monotonic effect limits or attributable usage for one action."""

    max_actions: int = Field(ge=0)
    max_strategy_attempts: int = Field(ge=0)
    max_travel_distance: float = Field(ge=0)
    max_blocks_changed: int = Field(ge=0)
    max_damage_taken: float = Field(ge=0)
    protected_items: tuple[str, ...] = ()
    resource_consumption: dict[str, int] = Field(default_factory=dict)

    def fits_within(self, limit: BudgetVector) -> bool:
        """Return whether every quantitative component is within ``limit``."""

        scalar_fits = (
            self.max_actions <= limit.max_actions
            and self.max_strategy_attempts <= limit.max_strategy_attempts
            and self.max_travel_distance <= limit.max_travel_distance
            and self.max_blocks_changed <= limit.max_blocks_changed
            and self.max_damage_taken <= limit.max_damage_taken
        )
        resources_fit = all(
            amount <= limit.resource_consumption.get(item, 0)
            for item, amount in self.resource_consumption.items()
        )
        return scalar_fits and resources_fit
