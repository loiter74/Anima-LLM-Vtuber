from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts.v2 import (
    ActionInspectionState,
    ActionReceipt,
    ActionRequest,
    ActionStatus,
    BudgetVector,
    CancellationAck,
    CapabilityDefinition,
    CapabilityGuarantees,
    EnvironmentProfile,
    GoalVerificationStatus,
    Observation,
    PostObservationStatus,
    ReceiptOutcome,
    ReconciliationStatus,
    RuntimeManifest,
    RuntimeProtocolError,
    SettlementSample,
    canonical_json_hash,
)


def _budget(**overrides: int | float) -> BudgetVector:
    values: dict[str, int | float] = {
        "max_actions": 4,
        "max_strategy_attempts": 1,
        "max_travel_distance": 32.0,
        "max_blocks_changed": 4,
        "max_damage_taken": 2.0,
    }
    values.update(overrides)
    return BudgetVector(**values)


def _profile() -> EnvironmentProfile:
    return EnvironmentProfile(
        runtime_protocol="2.0",
        minecraft_version="1.21.1",
        capability_schema_digest="a" * 64,
        skill_api_version="1",
        policy_version="1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
        modset_digest="d" * 64,
    )


def _manifest() -> RuntimeManifest:
    return RuntimeManifest(
        runtime_instance_id="runtime-instance-1",
        profile=_profile(),
        guarantees=CapabilityGuarantees(
            single_flight=True,
            correlation_idempotency=True,
            cooperative_cancellation=True,
            action_budget_enforcement=True,
            receipt_chains=True,
            correlation_inspection=True,
        ),
        capabilities=[
            CapabilityDefinition(
                name="collect",
                risk="survival_safe",
                effect_class="state_changing",
                parameters_schema={
                    "type": "object",
                    "properties": {"count": {"type": "integer", "minimum": 1}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
                receipt_schema_version="2",
                requires_post_observation=True,
                maximum_cost=_budget(max_actions=1),
            )
        ],
    )


def _request() -> ActionRequest:
    return ActionRequest(
        transport_id="transport-1",
        command_id="command-1",
        step_id="step-1",
        correlation_id="correlation-1",
        runtime_instance_id="runtime-instance-1",
        capability="collect",
        parameters={"count": 1},
        remaining_budget=_budget(),
        deadline_ms=1_800_000_000_000,
    )


def _observation(*, content_hash: str = "e" * 64) -> Observation:
    return Observation(
        observation_id="observation-1",
        correlation_id="correlation-observe-1",
        runtime_instance_id="runtime-instance-1",
        captured_at_ms=1_799_999_999_000,
        tick=42,
        action_sequence=7,
        content_hash=content_hash,
        profile=_profile(),
        world_identity={
            "runtime_instance_id": "runtime-instance-1",
            "server_identity_hash": "b" * 64,
            "world_identity_hash": "c" * 64,
            "dimension": "minecraft:overworld",
        },
        position={"x": 0.0, "y": 64.0, "z": 0.0},
        health=20.0,
        food=20,
        inventory={"oak_log": 1},
        equipment={},
        environment={"weather": "clear"},
    )


def _receipt(*, outcome: ReceiptOutcome = ReceiptOutcome.SUCCESS) -> ActionReceipt:
    return ActionReceipt(
        receipt_id="receipt-1",
        command_id="command-1",
        step_id="step-1",
        correlation_id="correlation-1",
        runtime_instance_id="runtime-instance-1",
        capability="collect",
        parameter_hash=canonical_json_hash({"count": 1}),
        action_sequence=8,
        started_at_ms=1_799_999_999_100,
        finished_at_ms=1_799_999_999_900,
        started_tick=43,
        finished_tick=48,
        outcome=outcome,
        post_observation="stable",
        reconciliation="accepted",
        goal_verification="unknown",
        reconciliation_error=None,
        settlement_trace=(),
        before_observation_hash="f" * 64,
        after_observation_hash="e" * 64,
        explained_mutations=[{"kind": "inventory", "subject": "oak_log", "delta": 1.0}],
        budget_usage=_budget(max_actions=1, max_travel_distance=2.0),
        previous_receipt_hash="",
        content_hash="1" * 64,
    )


def test_manifest_requires_every_v2_production_guarantee() -> None:
    manifest = _manifest()

    assert manifest.protocol_version == "2.0"
    assert manifest.capability("collect").requires_post_observation is True

    payload = manifest.model_dump(mode="json")
    payload["guarantees"]["single_flight"] = False
    with pytest.raises(ValidationError, match="single_flight"):
        RuntimeManifest.model_validate(payload)


def test_action_request_is_immutable_and_runtime_bound() -> None:
    request = _request()

    assert request.canonical_parameters_hash == canonical_json_hash({"count": 1})
    with pytest.raises(ValidationError):
        request.capability = "craft"


def test_budget_comparison_is_component_wise() -> None:
    reservation = _budget(max_actions=1, max_travel_distance=4.0)
    remaining = _budget(max_actions=2, max_travel_distance=8.0)

    assert reservation.fits_within(remaining)
    assert not remaining.fits_within(reservation)


def test_receipt_outcome_and_structured_error_are_consistent() -> None:
    payload = _receipt().model_dump(mode="json")
    payload["outcome"] = "error"

    with pytest.raises(ValidationError, match="error receipt requires"):
        ActionReceipt.model_validate(payload)

    payload["error"] = RuntimeProtocolError(
        code="RESOURCE_NOT_FOUND",
        message="tree missing",
        phase="runtime",
        outcome_known=True,
        world_may_have_changed=False,
        caller_may_resubmit=False,
        operator_action="inspect status",
    ).model_dump(mode="json")
    assert ActionReceipt.model_validate(payload).outcome is ReceiptOutcome.ERROR


def test_successful_receipt_can_wait_for_reconciliation_without_erasing_outcome() -> None:
    payload = _receipt().model_dump(mode="json")
    payload.update(
        post_observation="unstable",
        reconciliation="pending",
        goal_verification="unknown",
        reconciliation_error=RuntimeProtocolError(
            code="POST_ACTION_OBSERVATION_UNSTABLE",
            message="post-action state did not settle",
            phase="runtime",
            outcome_known=False,
            world_may_have_changed=True,
            caller_may_resubmit=False,
            operator_action="reconcile against a fresh stable observation",
        ).model_dump(mode="json"),
        settlement_trace=[
            SettlementSample(
                sample_index=0,
                captured_at_ms=1_799_999_999_901,
                position={"x": 8.0, "y": 59.0, "z": 5.0},
                on_ground=True,
                velocity={"x": 0.0, "y": 0.0, "z": 0.0},
                durable_state_hash="9" * 64,
                stable_streak=1,
                rejection_reason="durable_state_changed",
            ).model_dump(mode="json")
        ],
    )

    receipt = ActionReceipt.model_validate(payload)

    assert receipt.outcome is ReceiptOutcome.SUCCESS
    assert receipt.error is None
    assert receipt.post_observation is PostObservationStatus.UNSTABLE
    assert receipt.reconciliation is ReconciliationStatus.PENDING
    assert receipt.goal_verification is GoalVerificationStatus.UNKNOWN
    assert receipt.reconciliation_error is not None
    assert receipt.settlement_trace[0].stable_streak == 1


def test_attack_receipt_never_claims_success_without_terminal_combat_evidence() -> None:
    payload = _receipt().model_dump(mode="json")
    payload["capability"] = "attack"
    with pytest.raises(ValidationError, match="successful attack receipt"):
        ActionReceipt.model_validate(payload)

    payload["outcome"] = "unknown"
    payload["reconciliation"] = "pending"
    payload["error"] = RuntimeProtocolError(
        code="COMBAT_EVIDENCE_MISSING",
        message="combat ended without attributable terminal evidence",
        phase="runtime",
        outcome_known=False,
        world_may_have_changed=True,
        caller_may_resubmit=False,
        operator_action="reconcile combat from a fresh observation",
    ).model_dump(mode="json")
    assert ActionReceipt.model_validate(payload).combat is None


def test_terminal_action_status_returns_the_original_receipt() -> None:
    status = ActionStatus(
        runtime_instance_id="runtime-instance-1",
        correlation_id="correlation-1",
        state=ActionInspectionState.TERMINAL,
        request_hash="2" * 64,
        receipt=_receipt(),
        retained_until_ms=1_800_100_000_000,
    )

    assert status.receipt is not None and status.receipt.receipt_id == "receipt-1"

    payload = status.model_dump(mode="json")
    payload["receipt"] = None
    with pytest.raises(ValidationError, match="terminal action status requires"):
        ActionStatus.model_validate(payload)


def test_cancellation_ack_does_not_claim_terminal_cancellation() -> None:
    ack = CancellationAck(
        runtime_instance_id="runtime-instance-1",
        correlation_id="correlation-1",
        accepted=True,
        accepted_at_ms=1_799_999_999_500,
    )

    assert "cancelled" not in ack.model_dump()


def test_observation_carries_capture_order_and_stable_profile() -> None:
    observation = _observation()

    assert observation.captured_at == datetime.fromtimestamp(
        observation.captured_at_ms / 1000,
        tz=UTC,
    )
    assert observation.profile.dimension == "minecraft:overworld"
