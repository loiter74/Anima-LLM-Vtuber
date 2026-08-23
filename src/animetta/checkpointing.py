"""Lightweight durable-execution contracts shared by application services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

OwnerKind = Literal["turn", "program", "replay"]
Retention = Literal["temporary", "stable"]
_THREAD_ID = re.compile(r"^(turn|program|replay):[A-Za-z0-9_.:\-]{1,240}$")


@dataclass(frozen=True, slots=True)
class CheckpointRequest:
    """Describe one durable execution namespace without binding to LangGraph."""

    thread_id: str
    owner_kind: OwnerKind
    owner_id: str
    retention: Retention

    def __post_init__(self) -> None:
        if self.owner_kind not in {"turn", "program", "replay"}:
            raise ValueError("invalid checkpoint owner_kind")
        if self.retention not in {"temporary", "stable"}:
            raise ValueError("invalid checkpoint retention")
        if not _THREAD_ID.fullmatch(self.thread_id):
            raise ValueError("invalid checkpoint thread_id")
        if not self.thread_id.startswith(f"{self.owner_kind}:"):
            raise ValueError("checkpoint thread_id namespace must match owner_kind")
        if not self.owner_id or len(self.owner_id) > 240:
            raise ValueError("invalid checkpoint owner_id")


class CheckpointUnavailableError(RuntimeError):
    code = "CHECKPOINT_UNAVAILABLE"


class CheckpointConfigMismatchError(RuntimeError):
    code = "CHECKPOINT_CONFIG_MISMATCH"


__all__ = [
    "CheckpointConfigMismatchError",
    "CheckpointRequest",
    "CheckpointUnavailableError",
    "OwnerKind",
    "Retention",
]
