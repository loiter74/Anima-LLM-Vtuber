"""Tests for roleplay guard: drift detection and one-turn correction."""

import pytest

from animetta.orchestration.prompting.pipeline import compile as compile_prompt
from animetta.orchestration.prompting.roleplay_guard import (
    CORRECTION_SECTION,
    detect_drift,
    has_drift,
)

# ── Drift detection ──────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "作为 AI，我认为这个问题很好。",
    "我理解你的意思，但是...",
    "以下是几点建议：第一...",
    "总结一下，你的情况是...",
    "希望这能帮助你解决问题。",
    "作为助手，我建议你...",
])
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
