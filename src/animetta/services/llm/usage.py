"""Canonical provider usage and USD cost accounting."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.config.providers.llm.pricing import ModelPricingV1


class ModelUsageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    provider: str
    model: str
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated: bool
    cached_input_cost_usd: float = Field(ge=0)
    input_cost_usd: float = Field(ge=0)
    output_cost_usd: float = Field(ge=0)
    total_cost_usd: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_totals(self) -> ModelUsageV1:
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached input tokens cannot exceed input tokens")
        expected = self.cached_input_cost_usd + self.input_cost_usd + self.output_cost_usd
        if abs(self.total_cost_usd - expected) > 1e-12:
            raise ValueError("usage cost components do not sum to total")
        return self

    def observation_attributes(self) -> dict[str, str | int | float | bool]:
        return {f"usage_{key}": value for key, value in self.model_dump().items()}


def usage_from_response(
    response: Any,
    *,
    provider: str,
    model: str,
    pricing: ModelPricingV1 | None,
) -> ModelUsageV1 | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = int(
        getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0) or 0
    )
    output_tokens = int(
        getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0
    )
    details = getattr(usage, "prompt_tokens_details", None) or getattr(
        usage, "input_tokens_details", None
    )
    cached_tokens = int(
        getattr(usage, "prompt_cache_hit_tokens", None) or getattr(details, "cached_tokens", 0) or 0
    )
    cached_tokens = min(input_tokens, cached_tokens)
    estimated = bool(getattr(usage, "estimated", False))
    cached_cost = 0.0
    input_cost = 0.0
    output_cost = 0.0
    if pricing is not None:
        cached_cost = cached_tokens * pricing.cached_input_per_million / 1_000_000
        input_cost = (input_tokens - cached_tokens) * pricing.input_per_million / 1_000_000
        output_cost = output_tokens * pricing.output_per_million / 1_000_000
    total = cached_cost + input_cost + output_cost
    return ModelUsageV1(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        cached_input_tokens=cached_tokens,
        output_tokens=output_tokens,
        estimated=estimated,
        cached_input_cost_usd=cached_cost,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=total,
    )
