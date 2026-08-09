from animetta.observability.context import ObservationContext, observation_context
from animetta.observability.domain import PrivacyMode
from animetta.observability.ports import NoOpObservationRecorder
from animetta.orchestration.graph.tool_observation import (
    LedgerToolInvocationObserver,
    ToolInvocation,
    ToolInvocationCompletion,
)


class Recorder(NoOpObservationRecorder):
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    async def start_operation(self, record) -> None:
        self.started.append(record)

    async def finish_operation(self, record) -> None:
        self.finished.append(record)


def _context(mode: PrivacyMode) -> ObservationContext:
    return ObservationContext(
        trace_id="trace-1",
        operation_id="node-1",
        parent_operation_id=None,
        message_id="message-1",
        conversation_id="conversation-1",
        session_id="session-1",
        privacy_mode=mode,
    )


async def test_real_tool_call_records_one_full_operation_with_mcp_and_mc_identity() -> None:
    recorder = Recorder()
    observer = LedgerToolInvocationObserver(recorder, digest_salt="salt")
    invocation = ToolInvocation(
        tool_call_id="call-1",
        tool_name="mc_operate_bot",
        arguments={"operation": "execute", "api_key": "secret"},
        session_id="session-1",
        conversation_id="conversation-1",
        tool_source="mcp",
        mcp_server="minecraft",
    )

    with observation_context(_context(PrivacyMode.FULL)):
        await observer.before_invoke(invocation)
        await observer.after_invoke(
            ToolInvocationCompletion(
                invocation=invocation,
                result='{"command_id":"command-1","request_id":"request-1"}',
                error=None,
            )
        )

    assert len(recorder.started) == 1
    assert len(recorder.finished) == 1
    attributes = recorder.finished[0].attributes
    assert attributes["tool_source"] == "mcp"
    assert attributes["mcp_server"] == "minecraft"
    assert attributes["arguments_text"]
    assert attributes["minecraft_command_id"] == "command-1"


async def test_redacted_tool_call_keeps_only_length_and_digest() -> None:
    recorder = Recorder()
    observer = LedgerToolInvocationObserver(recorder, digest_salt="salt")
    invocation = ToolInvocation(
        tool_call_id="call-2",
        tool_name="search",
        arguments={"query": "private"},
        session_id="session-1",
        conversation_id="conversation-1",
    )

    with observation_context(_context(PrivacyMode.REDACTED)):
        await observer.before_invoke(invocation)
        await observer.after_invoke(
            ToolInvocationCompletion(invocation=invocation, result={"ok": True}, error=None)
        )

    attributes = recorder.finished[0].attributes
    assert attributes["arguments_text"] is None
    assert attributes["arguments_character_count"] > 0
    assert attributes["arguments_digest"]
    assert attributes["result_text"] is None
