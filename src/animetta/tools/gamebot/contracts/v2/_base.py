"""Shared primitives for the GameBot v2 contract."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, ConfigDict


class V2ContractModel(BaseModel):
    """Strict immutable base for values crossing the runtime boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_json(value: Any) -> str:
    """Return the cross-runtime canonical JSON representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    def normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: normalize(item[key]) for key in sorted(item)}
        if isinstance(item, (list, tuple)):
            return [normalize(value) for value in item]
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("canonical JSON forbids non-finite numbers")
            if item == 0:
                return 0
            if item.is_integer():
                return int(item)
        return item

    return json.dumps(normalize(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def canonical_json_hash(value: Any) -> str:
    """Hash canonical JSON with SHA-256."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
