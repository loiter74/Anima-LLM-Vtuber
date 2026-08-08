from __future__ import annotations

import pytest

from animetta.tools.minecraft.voyager.faults import (
    DeterministicFaultHarness,
    FaultScenario,
)
from animetta.tools.minecraft.voyager.reconciliation import (
    RecoveryDecision,
    decide_recovery,
)


def test_fault_harness_covers_every_named_fault() -> None:
    assert set(FaultScenario) == {
        FaultScenario.PRE_SEND_DISCONNECT,
        FaultScenario.POST_MUTATION_RESPONSE_LOSS,
        FaultScenario.PARTIAL_HASH_BROKEN_RECEIPT,
        FaultScenario.RUNTIME_INSTANCE_REPLACEMENT,
        FaultScenario.STALE_OBSERVATION,
        FaultScenario.CANCEL_ACK_STILL_BUSY,
        FaultScenario.UNEXPLAINED_DELTA,
        FaultScenario.SQLITE_FAILURE,
        FaultScenario.EVENT_PUBLISH_FAILURE,
    }


def test_runtime_faults_map_to_known_or_quarantined_recovery() -> None:
    harness = DeterministicFaultHarness()
    decisions = {
        scenario: decide_recovery(harness.evidence_for(scenario))
        for scenario in FaultScenario
        if harness.evidence_for(scenario) is not None
    }

    assert decisions[FaultScenario.PRE_SEND_DISCONNECT] is RecoveryDecision.KNOWN_NO_EFFECT
    assert (
        decisions[FaultScenario.POST_MUTATION_RESPONSE_LOSS]
        is RecoveryDecision.SUCCEEDED_RECONCILED
    )
    assert decisions[FaultScenario.CANCEL_ACK_STILL_BUSY] is RecoveryDecision.CANCEL_AND_REINSPECT
    for scenario in {
        FaultScenario.PARTIAL_HASH_BROKEN_RECEIPT,
        FaultScenario.RUNTIME_INSTANCE_REPLACEMENT,
        FaultScenario.STALE_OBSERVATION,
        FaultScenario.UNEXPLAINED_DELTA,
    }:
        assert decisions[scenario] is RecoveryDecision.BLOCKED_UNKNOWN


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        (FaultScenario.SQLITE_FAILURE, OSError),
        (FaultScenario.EVENT_PUBLISH_FAILURE, ConnectionError),
    ],
)
def test_non_runtime_faults_are_injectable(scenario, error) -> None:
    with pytest.raises(error):
        DeterministicFaultHarness().inject_non_runtime_failure(scenario)
