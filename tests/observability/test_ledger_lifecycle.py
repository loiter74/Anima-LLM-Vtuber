import time

import pytest

from animetta.observability.domain import (
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
    PrivacyMode,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from animetta.observability.ledger.sqlite import (
    LedgerIntegrityError,
    LedgerWriteError,
    SQLiteObservationLedger,
)


def _trace(trace_id: str = "task-1") -> TraceStarted:
    return TraceStarted(
        identity=TraceIdentity("message-1", "conversation-1", trace_id, "socket-1"),
        runtime_profile="golden",
        input_type="text",
        privacy_mode=PrivacyMode.REDACTED,
        started_at=time.time(),
    )


def _operation(
    operation_id: str,
    *,
    trace_id: str = "task-1",
    parent: str | None = None,
    critical_path: bool = True,
) -> OperationStarted:
    return OperationStarted(
        operation_id=operation_id,
        trace_id=trace_id,
        parent_operation_id=parent,
        layer=ObservationLayer.WORKFLOW,
        name=operation_id,
        critical_path=critical_path,
        started_at=time.time(),
    )


async def test_root_trace_is_durable_before_start_returns(tmp_path) -> None:
    ledger = SQLiteObservationLedger(tmp_path / "observations.db")
    await ledger.start()

    await ledger.start_trace(_trace())

    detail = await ledger.trace_detail("task-1")
    assert detail is not None
    assert detail["trace_id"] == "task-1"
    assert detail["outcome"] is None
    await ledger.close()


async def test_finalization_waits_for_prior_operations_and_is_immediately_queryable(
    tmp_path,
) -> None:
    ledger = SQLiteObservationLedger(tmp_path / "observations.db")
    await ledger.start()
    await ledger.start_trace(_trace())
    await ledger.start_operation(_operation("reasoner"))
    await ledger.finish_operation(
        OperationFinished("reasoner", OperationStatus.SUCCESS, time.time())
    )

    await ledger.finish_trace("task-1", TraceOutcome.SUCCESS, finished_at=time.time())

    detail = await ledger.trace_detail("task-1")
    assert detail is not None
    assert detail["outcome"] == "success"
    assert [item["name"] for item in detail["operations"]] == ["reasoner"]
    assert detail["operations"][0]["status"] == "success"
    await ledger.close()


async def test_trace_cannot_finalize_with_running_critical_operation(tmp_path) -> None:
    ledger = SQLiteObservationLedger(tmp_path / "observations.db")
    await ledger.start()
    await ledger.start_trace(_trace())
    await ledger.start_operation(_operation("reasoner"))

    with pytest.raises(LedgerIntegrityError, match="critical"):
        await ledger.finish_trace("task-1", TraceOutcome.SUCCESS, finished_at=time.time())

    await ledger.finish_operation(
        OperationFinished("reasoner", OperationStatus.CANCELLED, time.time())
    )
    await ledger.finish_trace("task-1", TraceOutcome.CANCELLED, finished_at=time.time())
    await ledger.close()


async def test_noncritical_memory_operation_can_append_after_trace_finalization(
    tmp_path,
) -> None:
    ledger = SQLiteObservationLedger(tmp_path / "observations.db")
    await ledger.start()
    await ledger.start_trace(_trace())
    await ledger.finish_trace("task-1", TraceOutcome.SUCCESS, finished_at=time.time())

    await ledger.start_operation(_operation("memory.ingest", critical_path=False))
    await ledger.finish_operation(
        OperationFinished("memory.ingest", OperationStatus.SUCCESS, time.time())
    )
    await ledger.flush()

    detail = await ledger.trace_detail("task-1")
    assert detail is not None
    assert detail["operations"][0]["critical_path"] is False
    assert detail["operations"][0]["name"] == "memory.ingest"
    await ledger.close()


async def test_invalid_parent_or_trace_surfaces_at_flush_and_degrades_health(tmp_path) -> None:
    ledger = SQLiteObservationLedger(tmp_path / "observations.db")
    await ledger.start()

    await ledger.start_operation(_operation("orphan", trace_id="missing"))

    with pytest.raises(LedgerWriteError):
        await ledger.flush()
    health = await ledger.health()
    assert health.degraded is True
    assert health.writer_errors == 1
    await ledger.close()


async def test_startup_marks_stale_running_trace_aborted(tmp_path) -> None:
    db_path = tmp_path / "observations.db"
    first = SQLiteObservationLedger(db_path)
    await first.start()
    await first.start_trace(_trace())
    await first.close()

    second = SQLiteObservationLedger(db_path)
    await second.start()
    detail = await second.trace_detail("task-1")

    assert detail is not None
    assert detail["outcome"] == "aborted"
    assert (await second.health()).stale_traces_recovered == 1
    await second.close()
