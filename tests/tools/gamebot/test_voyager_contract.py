"""Contracts that make Voyager progress attributable and transport-independent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot import contracts


def _observation(observation_id: str, *, inventory: dict[str, int] | None = None):
    return contracts.GameBotObservation(
        observation_id=observation_id,
        correlation_id=f"corr-{observation_id}",
        runtime_id="runtime-1",
        captured_at=datetime(2026, 7, 12, tzinfo=UTC),
        health=20,
        food=20,
        inventory=inventory or {},
        equipment={},
        environment={"biome": "plains"},
    )


def _receipt(
    receipt_id: str,
    *,
    correlation_id: str,
    before_hash: str,
    after_hash: str,
    previous_receipt_hash: str = "",
    session_id: str = "session-1",
    task_id: str = "task-1",
    runtime_id: str = "runtime-1",
):
    started = datetime(2026, 7, 12, tzinfo=UTC)
    return contracts.ActionReceipt(
        receipt_id=receipt_id,
        session_id=session_id,
        task_id=task_id,
        correlation_id=correlation_id,
        runtime_id=runtime_id,
        capability="collect",
        params={"block_type": "oak_log", "count": 1},
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        before_observation_hash=before_hash,
        after_observation_hash=after_hash,
        previous_receipt_hash=previous_receipt_hash,
        outcome=contracts.ActionOutcome.SUCCESS,
    )


def test_capability_manifest_preserves_risk_and_parameter_schema() -> None:
    manifest = contracts.CapabilityManifest(
        protocol_version="1.0",
        runtime_id="runtime-1",
        capabilities=[
            contracts.GameBotCapability(
                name="collect",
                risk=contracts.CapabilityRisk.SURVIVAL_SAFE,
                parameters={"block_type": {"type": "string"}, "count": {"type": "integer"}},
            ),
            contracts.GameBotCapability(
                name="reset_world",
                risk=contracts.CapabilityRisk.TEST_ADMIN,
                parameters={},
            ),
        ],
    )

    assert manifest.capability("collect").risk is contracts.CapabilityRisk.SURVIVAL_SAFE
    assert manifest.capability("collect").parameters["count"]["type"] == "integer"
    assert manifest.capability("reset_world").risk is contracts.CapabilityRisk.TEST_ADMIN


def test_observation_has_stable_content_hash_and_runtime_provenance() -> None:
    first = _observation("obs-1", inventory={"oak_log": 1})
    same_content = first.model_copy()
    changed = first.model_copy(update={"inventory": {"oak_log": 2}})

    assert first.content_hash == same_content.content_hash
    assert first.content_hash != changed.content_hash
    assert first.runtime_id == "runtime-1"


def test_action_error_is_machine_readable() -> None:
    error = contracts.ActionError(
        code="RESOURCE_NOT_FOUND",
        message="No oak log in bounded search area",
        retryable=True,
        details={"searched": 64},
    )

    receipt = _receipt(
        "receipt-1",
        correlation_id="corr-1",
        before_hash="before",
        after_hash="after",
    ).model_copy(update={"outcome": contracts.ActionOutcome.ERROR, "error": error})

    assert receipt.error.code == "RESOURCE_NOT_FOUND"
    assert receipt.error.retryable is True


def test_contracts_reject_missing_correlation_identifiers() -> None:
    with pytest.raises(ValidationError):
        contracts.GameBotObservation(
            observation_id="obs-1",
            correlation_id="",
            runtime_id="runtime-1",
            captured_at=datetime(2026, 7, 12, tzinfo=UTC),
        )

    with pytest.raises(ValidationError):
        _receipt(
            "receipt-1",
            correlation_id="",
            before_hash="before",
            after_hash="after",
        )


def test_receipt_chain_accepts_linked_same_task_receipts() -> None:
    first = _receipt(
        "receipt-1",
        correlation_id="corr-1",
        before_hash="obs-0",
        after_hash="obs-1",
    )
    second = _receipt(
        "receipt-2",
        correlation_id="corr-2",
        before_hash="obs-1",
        after_hash="obs-2",
        previous_receipt_hash=first.content_hash,
    )

    report = contracts.validate_receipt_chain(
        [first, second],
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert report.valid is True
    assert report.errors == []
    assert report.final_observation_hash == "obs-2"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"session_id": "session-other"}, "SESSION_MISMATCH"),
        ({"task_id": "task-other"}, "TASK_MISMATCH"),
        ({"runtime_id": "runtime-other"}, "RUNTIME_MISMATCH"),
        ({"previous_receipt_hash": "broken"}, "BROKEN_RECEIPT_LINK"),
        ({"before_observation_hash": "other"}, "BROKEN_OBSERVATION_LINK"),
    ],
)
def test_receipt_chain_rejects_unattributable_links(mutation: dict, expected_code: str) -> None:
    first = _receipt(
        "receipt-1",
        correlation_id="corr-1",
        before_hash="obs-0",
        after_hash="obs-1",
    )
    second = _receipt(
        "receipt-2",
        correlation_id="corr-2",
        before_hash="obs-1",
        after_hash="obs-2",
        previous_receipt_hash=first.content_hash,
    ).model_copy(update=mutation)

    report = contracts.validate_receipt_chain(
        [first, second],
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    assert report.valid is False
    assert expected_code in {error.code for error in report.errors}


def test_receipt_chain_rejects_duplicate_receipt_and_correlation_ids() -> None:
    first = _receipt(
        "receipt-1",
        correlation_id="corr-1",
        before_hash="obs-0",
        after_hash="obs-1",
    )
    duplicate = _receipt(
        "receipt-1",
        correlation_id="corr-1",
        before_hash="obs-1",
        after_hash="obs-2",
        previous_receipt_hash=first.content_hash,
    )

    report = contracts.validate_receipt_chain(
        [first, duplicate],
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    codes = {error.code for error in report.errors}
    assert "DUPLICATE_RECEIPT_ID" in codes
    assert "DUPLICATE_CORRELATION_ID" in codes


def test_skill_execution_result_preserves_ordered_receipt_chain() -> None:
    first = _receipt(
        "receipt-1",
        correlation_id="corr-1",
        before_hash="obs-0",
        after_hash="obs-1",
    )
    second = _receipt(
        "receipt-2",
        correlation_id="corr-2",
        before_hash="obs-1",
        after_hash="obs-2",
        previous_receipt_hash=first.content_hash,
    )

    result = contracts.SkillExecutionResult(
        receipts=[first, second],
        output={"collected": 1},
    )

    assert [receipt.receipt_id for receipt in result.receipts] == ["receipt-1", "receipt-2"]
    assert result.output == {"collected": 1}
