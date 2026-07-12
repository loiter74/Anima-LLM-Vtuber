import asyncio
import sqlite3
import time

from animetta.observability.domain import (
    EventDirection,
    ObservationEvent,
    PrivacyMode,
    TraceIdentity,
    TraceStarted,
)
from animetta.observability.ledger.sqlite import SQLiteObservationLedger


def _trace(trace_id: str) -> TraceStarted:
    return TraceStarted(
        identity=TraceIdentity("message", "conversation", trace_id, "socket"),
        runtime_profile="development",
        input_type="text",
        privacy_mode=PrivacyMode.FULL,
        started_at=time.time(),
    )


def _event(index: int) -> ObservationEvent:
    return ObservationEvent(
        event_id=f"event-{index}",
        trace_id="task-1",
        operation_id=None,
        direction=EventDirection.INTERNAL,
        name="queue.test",
        phase="test",
        occurred_at=time.time(),
        payload_size=0,
        identity_valid=True,
    )


async def test_noncritical_records_drop_under_real_sqlite_backpressure(tmp_path) -> None:
    db_path = tmp_path / "observations.db"
    ledger = SQLiteObservationLedger(db_path, queue_capacity=2, busy_timeout_ms=100)
    await ledger.start()
    await ledger.start_trace(_trace("task-1"))

    lock = sqlite3.connect(db_path, timeout=0.1)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        for index in range(20):
            await ledger.record_event(_event(index))
        await asyncio.sleep(0.05)
        health = await ledger.health()
    finally:
        lock.rollback()
        lock.close()

    assert health.dropped_records > 0
    await ledger.close()


async def test_critical_root_waits_for_capacity_instead_of_dropping(tmp_path) -> None:
    db_path = tmp_path / "observations.db"
    ledger = SQLiteObservationLedger(db_path, queue_capacity=1, busy_timeout_ms=500)
    await ledger.start()
    await ledger.start_trace(_trace("task-1"))

    lock = sqlite3.connect(db_path, timeout=0.1)
    lock.execute("BEGIN EXCLUSIVE")
    try:
        await ledger.record_event(_event(1))
        await asyncio.sleep(0.02)
        root_task = asyncio.create_task(ledger.start_trace(_trace("task-2")))
        await asyncio.sleep(0.05)
        assert root_task.done() is False
    finally:
        lock.rollback()
        lock.close()

    await asyncio.wait_for(root_task, timeout=2.0)
    assert await ledger.trace_detail("task-2") is not None
    await ledger.close()


async def test_shutdown_drains_accepted_records(tmp_path) -> None:
    db_path = tmp_path / "observations.db"
    first = SQLiteObservationLedger(db_path)
    await first.start()
    await first.start_trace(_trace("task-1"))
    await first.record_event(_event(1))
    await first.close()

    second = SQLiteObservationLedger(db_path)
    await second.start()
    detail = await second.trace_detail("task-1")

    assert detail is not None
    assert [event["event_id"] for event in detail["events"]] == ["event-1"]
    await second.close()
