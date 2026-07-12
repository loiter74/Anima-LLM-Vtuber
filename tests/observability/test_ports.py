from animetta.observability.domain import (
    EventDirection,
    ObservationEvent,
    PrivacyMode,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from animetta.observability.ports import (
    NoOpObservationMirror,
    NoOpObservationQuery,
    NoOpObservationRecorder,
    NoOpObservationReportStore,
    ObservationMirror,
    ObservationQuery,
    ObservationRecorder,
    ObservationReportStore,
)


def test_noop_implementations_satisfy_runtime_ports() -> None:
    assert isinstance(NoOpObservationRecorder(), ObservationRecorder)
    assert isinstance(NoOpObservationQuery(), ObservationQuery)
    assert isinstance(NoOpObservationReportStore(), ObservationReportStore)
    assert isinstance(NoOpObservationMirror(), ObservationMirror)


async def test_noop_recorder_accepts_complete_lifecycle() -> None:
    recorder = NoOpObservationRecorder()
    trace = TraceStarted(
        identity=TraceIdentity("m", "c", "t", "s"),
        runtime_profile="development",
        input_type="text",
        privacy_mode=PrivacyMode.FULL,
        started_at=1.0,
    )
    event = ObservationEvent(
        event_id="e",
        trace_id="t",
        operation_id=None,
        direction=EventDirection.INGRESS,
        name="chat:text",
        phase="ingress",
        occurred_at=1.1,
        payload_size=10,
        identity_valid=True,
    )

    await recorder.start_trace(trace)
    await recorder.record_event(event)
    await recorder.finish_trace("t", TraceOutcome.SUCCESS, finished_at=2.0)
    await recorder.flush()

    assert (await recorder.health()).enabled is False


async def test_noop_query_returns_versioned_empty_shapes() -> None:
    query = NoOpObservationQuery()

    assert (await query.overview())["schema_version"] == 2
    assert await query.recent_traces() == []
    assert await query.trace_detail("missing") is None
