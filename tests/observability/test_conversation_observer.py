from animetta.observability.conversation import (
    ConversationObserver,
    reduce_trace_outcome,
)
from animetta.observability.domain import PrivacyMode, TraceOutcome
from animetta.observability.ports import NoOpObservationRecorder


class Recorder(NoOpObservationRecorder):
    def __init__(self) -> None:
        self.started = []
        self.finished = []
        self.events = []
        self.flushes = 0

    async def start_trace(self, record) -> None:
        self.started.append(record)

    async def finish_trace(self, trace_id, outcome, **kwargs) -> None:
        self.finished.append((trace_id, outcome, kwargs))

    async def record_event(self, record) -> None:
        self.events.append(record)

    async def flush(self) -> None:
        self.flushes += 1


def _state() -> dict:
    return {
        "task_id": "task-canonical",
        "message_id": "message-1",
        "conversation_id": "conversation-1",
        "session_id": "socket-1",
        "input_type": "text",
        "user_text": "secret input",
    }


async def test_conversation_observer_uses_task_id_verbatim_and_flushes() -> None:
    recorder = Recorder()
    observer = ConversationObserver(
        recorder,
        runtime_profile="golden",
        digest_salt="test-salt",
    )

    turn = await observer.start(_state())
    await turn.finish({**_state(), "response_text": "secret output"})

    trace = recorder.started[0]
    assert trace.trace_id == "task-canonical"
    assert trace.privacy_mode is PrivacyMode.REDACTED
    assert trace.user_content.text is None
    assert recorder.finished[0][0] == "task-canonical"
    assert recorder.finished[0][1] is TraceOutcome.SUCCESS
    assert recorder.finished[0][2]["assistant_content"].text is None
    assert recorder.events[0].direction.value == "ingress"
    assert recorder.events[0].phase == "accepted"
    assert recorder.flushes == 1


def test_outcome_reduction_uses_state_and_required_delivery_evidence() -> None:
    assert reduce_trace_outcome({"error": "soft failure"}) is TraceOutcome.FAILED
    assert reduce_trace_outcome({"response_text": ""}) is TraceOutcome.FAILED
    assert (
        reduce_trace_outcome(
            {
                "response_text": "ok",
                "metadata": {"degradation_reason": "tts_unavailable"},
            }
        )
        is TraceOutcome.DEGRADED
    )
    assert (
        reduce_trace_outcome(
            {
                "response_text": "ok",
                "metadata": {
                    "delivery": {
                        "text_delivered": True,
                        "terminal_control_delivered": False,
                    }
                },
            }
        )
        is TraceOutcome.FAILED
    )
