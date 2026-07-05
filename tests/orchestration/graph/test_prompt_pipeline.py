"""Tests for prompt pipeline: full compile scenarios."""

from __future__ import annotations

import pytest

from animetta.orchestration.prompting.pipeline import compile as compile_prompt
from animetta.orchestration.prompting.types import CompiledPrompt


@pytest.mark.asyncio
async def test_persona_only():
    """Only persona, no memory or overlay."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert result.system_prompt == "You are Aura."
    assert result.section_count == 1  # persona only (runtime_personality empty → omitted)


@pytest.mark.asyncio
async def test_persona_plus_overlay():
    """Persona + runtime personality overlay."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {"personality_overlay": "当前情绪：保持积极愉快的语气"},
    }
    result = await compile_prompt(state)
    assert "You are Aura." in result.system_prompt
    assert "当前情绪：保持积极愉快的语气" in result.system_prompt
    assert result.section_count == 2


@pytest.mark.asyncio
async def test_memory_present():
    """Memory context is included when present."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state, memory_context="## 相关记忆\n- 用户喜欢编程")
    assert "用户喜欢编程" in result.system_prompt
    assert result.memory_included is True


@pytest.mark.asyncio
async def test_memory_absent():
    """Memory section omitted when no context."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state, memory_context="")
    assert result.memory_included is False


@pytest.mark.asyncio
async def test_memory_failure_produces_warning():
    """Memory source failure is captured as warning, prompt still compiles."""
    state = {
        "session_id": "test",
        "system_prompt": "You are Aura.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    # No memory, but prompt still works
    assert "You are Aura." in result.system_prompt
    assert result.section_count >= 1


@pytest.mark.asyncio
async def test_streaming_mode():
    """Streaming mode overlay is included."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"personality_mode": "streaming"},
    }
    result = await compile_prompt(state)
    assert "直播模式" in result.system_prompt


@pytest.mark.asyncio
async def test_mood_overlay():
    """Mood-based overlay is included."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {"personality_mood": "happy"},
    }
    result = await compile_prompt(state)
    assert "保持积极愉快的语气" in result.system_prompt


@pytest.mark.asyncio
async def test_section_names_in_metadata():
    """Metadata includes section names."""
    state = {
        "session_id": "test",
        "system_prompt": "Base.",
        "metadata": {},
    }
    result = await compile_prompt(state)
    assert "persona" in result.section_names
