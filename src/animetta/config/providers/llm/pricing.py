"""Versioned model pricing declarations used by production cost gates."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ModelPricingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    currency: str = "USD"
    cached_input_per_million: float = Field(ge=0)
    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)
    verified_on: date
    source: HttpUrl

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value != "USD":
            raise ValueError("agent cost gates currently require USD pricing")
        return value

    def is_stale(self, *, today: date | None = None, max_age_days: int = 90) -> bool:
        reference = today or date.today()
        return (reference - self.verified_on).days > max_age_days
