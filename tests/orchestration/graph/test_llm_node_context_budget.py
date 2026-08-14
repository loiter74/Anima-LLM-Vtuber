from __future__ import annotations

"""Tests for the graph-layer token budget (context-bloat guard).

Validates token counting and pair-atomic trimming for explicit conversation history.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from animetta.orchestration.graph.conversation_session import ConversationSessionState
from animetta.orchestration.graph.llm_node import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    _explicit_history_messages,
)
from animetta.services.llm.token_counting import (
    count_message_tokens,
    make_trim_token_counter,
)

# ── Token counting ────────────────────────────────────────────────────────


class TestTokenCounting:
    def test_counts_plain_dicts(self) -> None:
        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        tokens = count_message_tokens(messages)
        assert tokens > 0

    def test_counts_langchain_messages(self) -> None:
        messages = [
            HumanMessage(content="What is 2+2?"),
            AIMessage(content="It is 4."),
        ]
        tokens = count_message_tokens(messages)
        assert tokens > 0

    def test_empty_messages_is_zero(self) -> None:
        assert count_message_tokens([]) == 0

    def test_more_text_means_more_tokens(self) -> None:
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "hello " * 100}]
        assert count_message_tokens(long) > count_message_tokens(short)

    def test_make_trim_token_counter_returns_int(self) -> None:
        counter = make_trim_token_counter()
        result = counter([HumanMessage(content="test message")])
        assert isinstance(result, int)
        assert result > 0


# ── Explicit completed-pair budget ────────────────────────────────────────


def _make_state(**overrides) -> dict:
    state: dict = {}
    state.update(overrides)
    return state


class TestExplicitHistoryBudget:
    def test_default_budget_constant_is_reasonable(self) -> None:
        assert 1000 <= DEFAULT_CONTEXT_TOKEN_BUDGET <= 32000

    def test_no_session_preserves_current_tool_chain(self) -> None:
        current = [HumanMessage(content="current"), AIMessage(content="tool plan")]

        result = _explicit_history_messages(current, _make_state(), None, "test-session")

        assert result == current

    def test_zero_budget_keeps_all_completed_pairs(self) -> None:
        session = ConversationSessionState()
        for index in range(3):
            session.commit(
                task_id=f"task-{index}",
                user_text=f"user-{index}",
                final_response=f"assistant-{index}",
            )
        current = HumanMessage(content="current")
        config = {"configurable": {"conversation_session": session}}

        result = _explicit_history_messages(
            [current], _make_state(max_context_tokens=0), config, "test-session"
        )

        assert len(result) == 7
        assert result[-1] is current

    def test_completed_pairs_trim_atomically_and_keep_most_recent_pair(self) -> None:
        session = ConversationSessionState()
        for index in range(3):
            session.commit(
                task_id=f"task-{index}",
                user_text=f"user-{index} " * 80,
                final_response=f"assistant-{index} " * 80,
            )
        current = HumanMessage(content="current input must survive")
        system = SystemMessage(content="system prompt")
        latest = [
            HumanMessage(content=session.prompt_window[-1][0]),
            AIMessage(content=session.prompt_window[-1][1]),
        ]
        budget = make_trim_token_counter()([system, *latest, current])
        config = {"configurable": {"conversation_session": session}}

        result = _explicit_history_messages(
            [current],
            _make_state(max_context_tokens=budget),
            config,
            "test-session",
            fixed_messages=[system],
        )

        assert result[-1] is current
        historical = result[:-1]
        assert [message.content for message in historical] == [
            latest[0].content,
            latest[1].content,
        ]
        assert len(historical) % 2 == 0
        for index in range(0, len(historical), 2):
            assert isinstance(historical[index], HumanMessage)
            assert isinstance(historical[index + 1], AIMessage)
