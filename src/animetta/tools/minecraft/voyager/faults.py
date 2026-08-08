"""Deterministic fault scenarios shared by recovery and acceptance tests."""

from __future__ import annotations

from enum import StrEnum

from .reconciliation import RecoveryEvidence


class FaultScenario(StrEnum):
    PRE_SEND_DISCONNECT = "pre_send_disconnect"
    POST_MUTATION_RESPONSE_LOSS = "post_mutation_response_loss"
    PARTIAL_HASH_BROKEN_RECEIPT = "partial_hash_broken_receipt"
    RUNTIME_INSTANCE_REPLACEMENT = "runtime_instance_replacement"
    STALE_OBSERVATION = "stale_observation"
    CANCEL_ACK_STILL_BUSY = "cancel_ack_still_busy"
    UNEXPLAINED_DELTA = "unexplained_delta"
    SQLITE_FAILURE = "sqlite_failure"
    EVENT_PUBLISH_FAILURE = "event_publish_failure"


class DeterministicFaultHarness:
    def evidence_for(self, scenario: FaultScenario) -> RecoveryEvidence | None:
        cases = {
            FaultScenario.PRE_SEND_DISCONNECT: RecoveryEvidence(
                same_instance=True,
                inspection_state="not_found",
                retention_guarantee_intact=True,
                action_was_accepted=False,
            ),
            FaultScenario.POST_MUTATION_RESPONSE_LOSS: RecoveryEvidence(
                same_instance=True,
                inspection_state="terminal",
                receipt_outcome="success",
                receipt_valid=True,
                usage_within_reservation=True,
                idle=True,
                observation_fresh=True,
            ),
            FaultScenario.PARTIAL_HASH_BROKEN_RECEIPT: RecoveryEvidence(
                same_instance=True,
                inspection_state="terminal",
                receipt_valid=False,
            ),
            FaultScenario.RUNTIME_INSTANCE_REPLACEMENT: RecoveryEvidence(
                same_instance=False,
                inspection_state="not_found",
            ),
            FaultScenario.STALE_OBSERVATION: RecoveryEvidence(
                same_instance=True,
                inspection_state="terminal",
                receipt_valid=True,
                usage_within_reservation=True,
                idle=True,
                observation_fresh=False,
            ),
            FaultScenario.CANCEL_ACK_STILL_BUSY: RecoveryEvidence(
                same_instance=True,
                inspection_state="running",
            ),
            FaultScenario.UNEXPLAINED_DELTA: RecoveryEvidence(
                same_instance=True,
                inspection_state="terminal",
                receipt_valid=True,
                usage_within_reservation=True,
                idle=True,
                observation_fresh=True,
                mutations_explained=False,
            ),
        }
        return cases.get(scenario)

    def inject_non_runtime_failure(self, scenario: FaultScenario) -> None:
        if scenario is FaultScenario.SQLITE_FAILURE:
            raise OSError("deterministic SQLite write failure")
        if scenario is FaultScenario.EVENT_PUBLISH_FAILURE:
            raise ConnectionError("deterministic event publish failure")
        raise ValueError(f"not a non-runtime fault: {scenario}")
