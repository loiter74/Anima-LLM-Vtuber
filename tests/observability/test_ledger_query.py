import time

import pytest

from animetta.observability.domain import (
    EventDirection,
    ObservationEvent,
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
    PrivacyMode,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from animetta.observability.ledger import SQLiteObservationLedger


@pytest.fixture
async def ledger(tmp_path):
    instance = SQLiteObservationLedger(tmp_path / "observations.db")
    await instance.start()
    try:
        yield instance
    finally:
        await instance.close()


def _trace(trace_id: str = "task-query") -> TraceStarted:
    return TraceStarted(
        identity=TraceIdentity("message-1", "conversation-1", trace_id, "socket-1"),
        runtime_profile="golden",
        input_type="text",
        privacy_mode=PrivacyMode.REDACTED,
        started_at=time.time(),
    )


async def test_query_returns_aggregates_tree_events_and_post_turn_state(ledger) -> None:
    await ledger.start_trace(_trace())
    await ledger.start_operation(
        OperationStarted(
            "reasoner",
            "task-query",
            None,
            ObservationLayer.WORKFLOW,
            "reasoner",
            True,
            time.time(),
        )
    )
    await ledger.start_operation(
        OperationStarted(
            "llm",
            "task-query",
            "reasoner",
            ObservationLayer.SERVICE,
            "llm.chat_messages",
            True,
            time.time(),
            provider="openai",
            model="gpt-test",
        )
    )
    await ledger.finish_operation(
        OperationFinished("llm", OperationStatus.SUCCESS, time.time())
    )
    await ledger.finish_operation(
        OperationFinished("reasoner", OperationStatus.SUCCESS, time.time())
    )
    await ledger.record_event(
        ObservationEvent(
            "event-1",
            "task-query",
            "reasoner",
            EventDirection.EGRESS,
            "chat:response",
            "delivered",
            time.time(),
            24,
            True,
        )
    )
    await ledger.finish_trace(
        "task-query", TraceOutcome.SUCCESS, finished_at=time.time()
    )
    await ledger.start_operation(
        OperationStarted(
            "memory",
            "task-query",
            None,
            ObservationLayer.MEMORY,
            "memory.ingest",
            False,
            time.time(),
        )
    )
    await ledger.flush()

    aggregates = await ledger.operation_aggregates()
    detail = await ledger.trace_detail("task-query")
    events = await ledger.trace_events("task-query")

    assert {(row["layer"], row["name"]) for row in aggregates} >= {
        ("workflow", "reasoner"),
        ("service", "llm.chat_messages"),
    }
    assert detail is not None
    assert detail["operation_tree"][0]["name"] == "reasoner"
    assert detail["operation_tree"][0]["children"][0]["name"] == "llm.chat_messages"
    assert detail["post_turn"]["pending"] == 1
    assert detail["post_turn"]["operations"][0]["name"] == "memory.ingest"
    assert events[0]["name"] == "chat:response"


async def test_query_lists_inspection_reports(ledger) -> None:
    now = time.time()
    await ledger.store_inspection_report(
        {
            "run_id": "run-1",
            "started_at": now,
            "finished_at": now + 1,
            "overall_ok": True,
            "checks": {"ledger": {"ok": True}},
        }
    )

    reports = await ledger.inspection_reports(limit=10)

    assert reports[0]["run_id"] == "run-1"
    assert reports[0]["checks"]["ledger"]["ok"] is True
