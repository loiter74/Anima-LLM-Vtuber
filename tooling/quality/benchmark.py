from __future__ import annotations

import math
from typing import Literal

from pydantic import Field

from .models import AggregateStatus, FrozenModel, Tier


class BenchmarkRun(FrozenModel):
    index: int = Field(ge=1)
    status: AggregateStatus
    wall_seconds: float = Field(ge=0)
    critical_path_seconds: float = Field(ge=0)
    cache_hit_ratio: float = Field(ge=0, le=1)
    cache_hit_groups: tuple[str, ...]


class BenchmarkEvidence(FrozenModel):
    schema_version: Literal[1] = 1
    tier: Tier
    plan_hash: str
    warm_run_count: int = Field(ge=1)
    planning_seconds: float = Field(ge=0)
    priming_wall_seconds: float = Field(ge=0)
    warm_runs: tuple[BenchmarkRun, ...]
    warm_p50_seconds: float = Field(ge=0)
    warm_p95_seconds: float = Field(ge=0)
    cache_hit_ratio: float = Field(ge=0, le=1)
    target_p95_seconds: float = Field(gt=0)
    target_planning_seconds: float = Field(gt=0)
    targets_met: bool


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]
