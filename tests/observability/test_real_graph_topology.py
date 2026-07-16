import pytest

import animetta.orchestration.graph.builder as builder
from animetta.observability.conversation import ConversationObserver
from animetta.observability.ledger import SQLiteObservationLedger
from animetta.orchestration.graph.state import create_initial_state


@pytest.mark.parametrize(
    ("golden", "expected"),
    [
        (
            False,
            [
                "conversation_start",
                "personality",
                "llm",
                "humor_rewrite",
                "humor_validation",
                "reply_output",
                "tts",
                "emotion",
                "output",
            ],
        ),
        (
            True,
            [
                "conversation_start",
                "personality",
                "reasoner",
                "anima_composer",
                "response_guard",
                "reply_output",
                "tts",
                "emotion",
                "performance_output",
                "conversation_finalizer",
            ],
        ),
    ],
)
async def test_committed_operations_equal_nodes_actually_run(
    tmp_path, monkeypatch, golden, expected
) -> None:
    async def node(state, config=None):
        return {"response_text": state.get("response_text") or "ok"}

    for name in {
        "asr_node",
        "personality_node",
        "llm_node",
        "humor_rewrite_node",
        "humor_validation_node",
        "tool_node",
        "tts_node",
        "emotion_node",
        "output_node",
        "conversation_start_node",
        "reasoner_node",
        "anima_composer_node",
        "response_guard_node",
        "reply_output_node",
        "performance_output_node",
        "conversation_finalizer_node",
    }:
        monkeypatch.setattr(builder, name, node)

    ledger = SQLiteObservationLedger(tmp_path / "observations.db")
    await ledger.start()
    try:
        graph = builder.build_graph(
            golden_profile=golden,
            observation_recorder=ledger,
        )
        state = create_initial_state(
            session_id="socket-1",
            input_type="text",
            user_text="hello",
            message_id="message-1",
            conversation_id="conversation-1",
            task_id="task-1",
        )
        turn = await ConversationObserver(
            ledger,
            runtime_profile="golden" if golden else "development",
            digest_salt="test-salt",
        ).start(state)
        result = await graph.ainvoke(state)
        await turn.finish(result)

        detail = await ledger.trace_detail("task-1")
        assert detail is not None
        assert [operation["name"] for operation in detail["operations"]] == expected
        assert {operation["trace_id"] for operation in detail["operations"]} == {"task-1"}
    finally:
        await ledger.close()
