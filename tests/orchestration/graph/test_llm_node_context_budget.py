from __future__ import annotations

"""Tests for the graph-layer token budget (context-bloat guard).

Validates both the token-counting utility and the ``_apply_context_budget``
helper that bounds ``state["messages"]`` before the LLM call. This is the
defense-in-depth layer alongside the provider-level ``max_history_messages``.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from animetta.orchestration.graph.llm_node import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    _apply_context_budget,
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


# ── _apply_context_budget ─────────────────────────────────────────────────


def _make_state(**overrides) -> dict:
    state: dict = {}
    state.update(overrides)
    return state


def _build_long_conversation(turns: int) -> list:
    """Build a conversation with enough turns to exceed a small budget."""
    messages = [SystemMessage(content="You are a helpful assistant.")]
    for i in range(turns):
        messages.append(HumanMessage(content=f"This is message number {i}. " * 20))
        messages.append(AIMessage(content=f"Here is my response to message {i}. " * 20))
    return messages


class TestApplyContextBudget:
    def test_noop_when_under_budget(self) -> None:
        messages = [HumanMessage(content="short"), AIMessage(content="reply")]
        state = _make_state()
        result = _apply_context_budget(messages, state, "test-session")
        assert result == messages

    def test_trims_when_over_budget(self) -> None:
        messages = _build_long_conversation(30)
        state = _make_state(max_context_tokens=500)
        result = _apply_context_budget(messages, state, "test-session")
        counter = make_trim_token_counter()
        assert counter(result) <= 500
        assert len(result) < len(messages)

    def test_preserves_system_message(self) -> None:
        """SystemMessage must survive trimming (include_system=True)."""
        system_content = "You are a helpful assistant."
        messages = [SystemMessage(content=system_content)]
        messages.extend(_build_long_conversation(30)[1:])  # skip dup system
        state = _make_state(max_context_tokens=500)
        result = _apply_context_budget(messages, state, "test-session")
        system_msgs = [m for m in result if isinstance(m, SystemMessage)]
        assert any(system_content in m.content for m in system_msgs)

    def test_preserves_most_recent_messages(self) -> None:
        """strategy='last' keeps the tail of the conversation."""
        messages = _build_long_conversation(20)
        last_human = messages[-2].content[:30]
        state = _make_state(max_context_tokens=800)
        result = _apply_context_budget(messages, state, "test-session")
        assert any(last_human in m.content for m in result)

    def test_zero_budget_disables_trimming(self) -> None:
        messages = [HumanMessage(content="test")]
        state = _make_state(max_context_tokens=0)
        result = _apply_context_budget(messages, state, "test-session")
        assert result == messages

    def test_single_message_not_trimmed(self) -> None:
        messages = [HumanMessage(content="only message")]
        state = _make_state(max_context_tokens=1)
        result = _apply_context_budget(messages, state, "test-session")
        assert len(result) == 1

    def test_default_budget_constant_is_reasonable(self) -> None:
        """The default budget should leave room for generation (< model context)."""
        assert 1000 <= DEFAULT_CONTEXT_TOKEN_BUDGET <= 32000
