"""Tests for prompt and memory pressure controls."""

import pytest

from animetta.orchestration.prompting.pipeline import compile as compile_prompt


@pytest.mark.asyncio
async def test_persona_before_memory():
    """Persona and correction sections appear before memory."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Anima.",
        "metadata": {},
    }
    result = await compile_prompt(
        state,
        memory_context="## 相关记忆\n- some memory",
    )
    persona_pos = result.system_prompt.index("You are Anima.")
    memory_pos = result.system_prompt.index("相关记忆")
    assert persona_pos < memory_pos


@pytest.mark.asyncio
async def test_memory_capped_in_realtime():
    """Long memory is truncated in realtime mode."""
    long_memory = "## 相关记忆\n" + "\n".join(f"- item {i}" * 20 for i in range(20))
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"personality_mode": "default"},
    }
    result = await compile_prompt(state, memory_context=long_memory)
    assert "记忆已截断" in result.system_prompt
    assert any("truncated" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_short_memory_not_capped():
    """Short memory passes through unchanged."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(
        state,
        memory_context="## 相关记忆\n- short",
    )
    assert "记忆已截断" not in result.system_prompt


@pytest.mark.asyncio
async def test_no_duplicate_system_prompts():
    """Compiled prompt should not contain the base system prompt twice."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Anima, the last witch.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    count = result.system_prompt.count("You are Anima, the last witch.")
    assert count == 1
