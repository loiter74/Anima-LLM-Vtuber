"""Tests for roleplay guard: drift detection and one-turn correction."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from animetta.orchestration.graph.conversation_session import ConversationSessionState
from animetta.orchestration.graph.personality_node import (
    _detect_previous_turn_drift,
    personality_node,
)
from animetta.orchestration.prompting.pipeline import compile as compile_prompt
from animetta.orchestration.prompting.roleplay_guard import (
    CORRECTION_SECTION,
    detect_drift,
    has_drift,
)

# ── Drift detection ──────────────────────────────────────────


@pytest.mark.parametrize(
    "phrase",
    [
        "作为 AI，我认为这个问题很好。",
        "我理解你的意思，但是...",
        "以下是几点建议：第一...",
        "总结一下，你的情况是...",
        "希望这能帮助你解决问题。",
        "作为助手，我建议你...",
    ],
)
def test_forbidden_phrases_trigger_drift(phrase):
    assert has_drift(phrase) is True
    assert len(detect_drift(phrase)) >= 1


def test_clean_anima_output_no_drift():
    text = "……嗯。但我不是很在意天气。[neutral]"
    assert has_drift(text) is False
    assert detect_drift(text) == []


def test_roleplay_voice_no_drift():
    text = "需求文档呢？没有文档就想要输出，这不是编程是许愿。"
    assert has_drift(text) is False


# ── Correction section ordering ──────────────────────────────


@pytest.mark.asyncio
async def test_correction_appears_before_memory():
    state = {
        "session_id": "test",
        "system_prompt": "You are Anima.",
        "metadata": {
            "roleplay_correction": CORRECTION_SECTION,
        },
    }
    result = await compile_prompt(
        state,
        memory_context="## 相关记忆\n- 用户喜欢编程",
    )
    # Correction (priority 250) must appear before memory (priority 300)
    correction_pos = result.system_prompt.index("角色回归提醒")
    memory_pos = result.system_prompt.index("相关记忆")
    assert correction_pos < memory_pos


@pytest.mark.asyncio
async def test_no_correction_when_clean():
    state = {
        "session_id": "test",
        "system_prompt": "You are Anima.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert "角色回归提醒" not in result.system_prompt


@pytest.mark.asyncio
async def test_correction_expires_after_one_turn():
    """Correction is not persisted — only present when explicitly set in metadata."""
    # Turn 1: drift detected, correction set
    state1 = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"roleplay_correction": CORRECTION_SECTION},
    }
    r1 = await compile_prompt(state1)
    assert "角色回归提醒" in r1.system_prompt

    # Turn 2: correction not set (expired)
    state2 = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    r2 = await compile_prompt(state2)
    assert "角色回归提醒" not in r2.system_prompt


# ── personality_node integration: drift → metadata → correction section ──


class TestPersonalityNodeDriftWiring:
    """Verify personality_node feeds roleplay_correction into the pipeline.

    This closes the dead-code gap noted during the bug audit: ``detect_drift``
    existed but no node populated ``metadata.roleplay_correction``, so the
    correction section never fired in production.
    """

    def test_no_messages_returns_empty(self):
        """First turn (no history) → no correction."""
        assert _detect_previous_turn_drift({"messages": [], "metadata": {}}) == ""

    def test_clean_ai_turn_returns_empty(self):
        """In-character AI reply → no correction."""
        state = {"messages": [AIMessage(content="……嗯。酒馆还没开门。")]}
        assert _detect_previous_turn_drift(state) == ""

    def test_drifted_ai_turn_returns_correction(self):
        """Assistant-flavor AI reply → CORRECTION_SECTION injected."""
        state = {"messages": [AIMessage(content="作为 AI，我认为这个问题很好。")]}
        result = _detect_previous_turn_drift(state)
        assert result == CORRECTION_SECTION

    def test_human_message_only_returns_empty(self):
        """No AIMessage in history → no correction (don't trip on user turns)."""
        state = {"messages": [HumanMessage(content="作为 AI 你怎么看")]}
        assert _detect_previous_turn_drift(state) == ""

    def test_uses_most_recent_ai_message(self):
        """Only the last AIMessage is checked (oldest drift is forgiven)."""
        state = {
            "messages": [
                AIMessage(content="作为 AI，我曾经这样说过。"),  # old drift
                AIMessage(content="……少管闲事。"),  # recent, clean
            ]
        }
        assert _detect_previous_turn_drift(state) == ""

    @pytest.mark.asyncio
    async def test_pipeline_sees_correction_after_drift(self):
        """End-to-end: drifted previous turn → compiled prompt contains correction.

        Simulates the real flow: personality_node runs, sets
        ``metadata.roleplay_correction``, then the prompt pipeline compiles
        and the correction section appears in the system prompt.
        """
        # ── Turn N: a drifted reply was produced ──
        state_after_drift = {
            "session_id": "test",
            "system_prompt": "You are Anima.",
            "messages": [AIMessage(content="作为助手，我建议你重启试试。")],
            "metadata": {},
            "channel_id": "",
            "persona": {},
        }

        # ── Turn N+1: personality_node runs first ──
        updated = await personality_node(state_after_drift, None)
        md = updated.get("metadata", {})

        # The correction must have been written
        assert "roleplay_correction" in md
        assert "角色回归提醒" in md["roleplay_correction"]

        # ── Then llm_node runs and compiles the prompt ──
        state_for_prompt = {**state_after_drift, "metadata": md}
        compiled = await compile_prompt(state_for_prompt)

        assert "角色回归提醒" in compiled.system_prompt, (
            "Correction section must reach the compiled system prompt"
        )

    @pytest.mark.asyncio
    async def test_no_correction_after_clean_turn(self):
        """Regression: clean reply must NOT trigger the correction section."""
        state_clean = {
            "session_id": "test",
            "system_prompt": "You are Anima.",
            "messages": [AIMessage(content="需求文档呢？没有文档就想要输出，这不是编程是许愿。")],
            "metadata": {},
            "channel_id": "",
            "persona": {},
        }

        updated = await personality_node(state_clean, None)
        md = updated.get("metadata", {})
        assert md.get("roleplay_correction", "") == ""

        state_for_prompt = {**state_clean, "metadata": md}
        compiled = await compile_prompt(state_for_prompt)
        assert "角色回归提醒" not in compiled.system_prompt


def test_drift_detection_reads_latest_committed_session_response() -> None:
    session = ConversationSessionState()
    session.commit(task_id="task", user_text="你好", final_response="作为 AI，我可以帮助你。")
    config = {"configurable": {"conversation_session": session}}
    result = _detect_previous_turn_drift({"messages": [], "metadata": {}}, config)
    assert result == CORRECTION_SECTION
