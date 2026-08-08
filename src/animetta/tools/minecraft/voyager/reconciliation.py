"""Pure recovery decision matrix for ambiguous GameBot v2 outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class RecoveryDecision(StrEnum):
    SUCCEEDED_RECONCILED = "succeeded_reconciled"
    FAILED_RECONCILED = "failed_reconciled"
    CANCELLED_RECONCILED = "cancelled_reconciled"
    KNOWN_NO_EFFECT = "known_no_effect"
    READ_RECONCILED = "read_reconciled"
    CANCEL_AND_REINSPECT = "cancel_and_reinspect"
    BLOCKED_UNKNOWN = "blocked_unknown"


@dataclass(frozen=True)
class RecoveryEvidence:
    same_instance: bool
    inspection_state: Literal["not_found", "accepted", "running", "terminal"]
    effect_class: Literal["read_only", "state_changing"] = "state_changing"
    receipt_outcome: Literal["success", "error", "cancelled", "unknown"] | None = None
    receipt_reconciliation: Literal["accepted", "pending", "quarantined"] = "accepted"
    receipt_valid: bool = False
    usage_within_reservation: bool = False
    idle: bool = False
    observation_fresh: bool = False
    observation_stable: bool = True
    mutations_explained: bool = True
    retention_guarantee_intact: bool = False
    action_was_accepted: bool = True


def decide_recovery(evidence: RecoveryEvidence) -> RecoveryDecision:
    if not evidence.same_instance:
        return RecoveryDecision.BLOCKED_UNKNOWN
    if evidence.inspection_state in {"accepted", "running"}:
        return RecoveryDecision.CANCEL_AND_REINSPECT
    if evidence.effect_class == "read_only" and evidence.inspection_state == "not_found":
        if evidence.idle and evidence.observation_fresh:
            return RecoveryDecision.READ_RECONCILED
        return RecoveryDecision.BLOCKED_UNKNOWN
    if evidence.inspection_state == "not_found":
        if evidence.retention_guarantee_intact and not evidence.action_was_accepted:
            return RecoveryDecision.KNOWN_NO_EFFECT
        return RecoveryDecision.BLOCKED_UNKNOWN
    if not evidence.receipt_valid or not evidence.usage_within_reservation:
        return RecoveryDecision.BLOCKED_UNKNOWN
    if evidence.receipt_reconciliation == "quarantined":
        return RecoveryDecision.BLOCKED_UNKNOWN
    if evidence.receipt_reconciliation == "pending" and not evidence.observation_stable:
        return RecoveryDecision.BLOCKED_UNKNOWN
    if not evidence.idle or not evidence.observation_fresh or not evidence.mutations_explained:
        return RecoveryDecision.BLOCKED_UNKNOWN
    if evidence.receipt_outcome == "success":
        return RecoveryDecision.SUCCEEDED_RECONCILED
    if evidence.receipt_outcome == "error":
        return RecoveryDecision.FAILED_RECONCILED
    if evidence.receipt_outcome == "cancelled":
        return RecoveryDecision.CANCELLED_RECONCILED
    return RecoveryDecision.BLOCKED_UNKNOWN
