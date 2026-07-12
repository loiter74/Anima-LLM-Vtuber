"""Trust-boundary contracts for autonomous game-bot sessions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .status import GameBotPosition


class CapabilityRisk(StrEnum):
    """Runtime capability risk classification."""

    SURVIVAL_SAFE = "survival_safe"
    TEST_ADMIN = "test_admin"
    FORBIDDEN = "forbidden"


class GameBotCapability(BaseModel):
    """A versioned action exposed by a game-bot runtime."""

    name: str = Field(min_length=1)
    risk: CapabilityRisk
    parameters: dict[str, Any] = Field(default_factory=dict)


class CapabilityManifest(BaseModel):
    """Capabilities and identity advertised by a connected runtime."""

    protocol_version: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    capabilities: list[GameBotCapability] = Field(default_factory=list)

    def capability(self, name: str) -> GameBotCapability:
        for capability in self.capabilities:
            if capability.name == name:
                return capability
        raise KeyError(name)


def _content_hash(model: BaseModel) -> str:
    def canonicalize(value: Any) -> Any:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, list):
            return [canonicalize(item) for item in value]
        if isinstance(value, dict):
            return {key: canonicalize(item) for key, item in value.items()}
        return value

    encoded = json.dumps(
        canonicalize(model.model_dump(mode="json")),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GameBotObservation(BaseModel):
    """Attributable world state obtained without administrator mutation."""

    observation_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    captured_at: datetime
    position: GameBotPosition | None = None
    health: float | None = None
    food: int | None = None
    inventory: dict[str, int] = Field(default_factory=dict)
    equipment: dict[str, str] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return _content_hash(self)


class ActionOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class ActionError(BaseModel):
    """Machine-readable action failure."""

    code: str = Field(min_length=1)
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ActionReceipt(BaseModel):
    """Evidence emitted for one runtime capability invocation."""

    receipt_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime
    before_observation_hash: str = Field(min_length=1)
    after_observation_hash: str = Field(min_length=1)
    previous_receipt_hash: str = ""
    outcome: ActionOutcome
    error: ActionError | None = None

    @property
    def content_hash(self) -> str:
        return _content_hash(self)


class SkillExecutionResult(BaseModel):
    """Ordered safe-wrapper receipts emitted by one generated skill execution."""

    receipts: list[ActionReceipt] = Field(default_factory=list)
    output: Any = None


class ReceiptChainError(BaseModel):
    code: str
    receipt_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ReceiptChainReport(BaseModel):
    valid: bool
    errors: list[ReceiptChainError] = Field(default_factory=list)
    final_observation_hash: str | None = None


def validate_receipt_chain(
    receipts: list[ActionReceipt],
    *,
    session_id: str,
    task_id: str,
    runtime_id: str,
) -> ReceiptChainReport:
    """Validate identity, uniqueness, and hash links for one task receipt chain."""

    errors: list[ReceiptChainError] = []
    seen_receipts: set[str] = set()
    seen_correlations: set[str] = set()
    previous: ActionReceipt | None = None

    for receipt in receipts:
        if receipt.receipt_id in seen_receipts:
            errors.append(ReceiptChainError(code="DUPLICATE_RECEIPT_ID", receipt_id=receipt.receipt_id))
        seen_receipts.add(receipt.receipt_id)

        if receipt.correlation_id in seen_correlations:
            errors.append(
                ReceiptChainError(code="DUPLICATE_CORRELATION_ID", receipt_id=receipt.receipt_id)
            )
        seen_correlations.add(receipt.correlation_id)

        for actual, expected, code in (
            (receipt.session_id, session_id, "SESSION_MISMATCH"),
            (receipt.task_id, task_id, "TASK_MISMATCH"),
            (receipt.runtime_id, runtime_id, "RUNTIME_MISMATCH"),
        ):
            if actual != expected:
                errors.append(
                    ReceiptChainError(
                        code=code,
                        receipt_id=receipt.receipt_id,
                        details={"expected": expected, "actual": actual},
                    )
                )

        if previous is None:
            if receipt.previous_receipt_hash:
                errors.append(
                    ReceiptChainError(code="BROKEN_RECEIPT_LINK", receipt_id=receipt.receipt_id)
                )
        else:
            if receipt.previous_receipt_hash != previous.content_hash:
                errors.append(
                    ReceiptChainError(code="BROKEN_RECEIPT_LINK", receipt_id=receipt.receipt_id)
                )
            if receipt.before_observation_hash != previous.after_observation_hash:
                errors.append(
                    ReceiptChainError(code="BROKEN_OBSERVATION_LINK", receipt_id=receipt.receipt_id)
                )
        previous = receipt

    if not receipts:
        errors.append(ReceiptChainError(code="EMPTY_RECEIPT_CHAIN"))

    return ReceiptChainReport(
        valid=not errors,
        errors=errors,
        final_observation_hash=receipts[-1].after_observation_hash if receipts else None,
    )
