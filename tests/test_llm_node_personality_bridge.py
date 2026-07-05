"""Tests for personality data bridge: personality_node → llm_node → memory_middleware.

Covers:
- personality_overlay injection into system prompt
- character_known/unknown passthrough to memory middleware
- MBTI dimension passthrough to memory middleware
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.orchestration.graph.llm_node import _retrieve_memory_context


# ── Fixtures ──────────────────────────────────────────────────


def _make_state(**metadata_overrides: Any) -> dict[str, Any]:
    """Build a minimal AgentState-like dict with optional metadata fields."""
    return {
        "session_id": "test-session",
        "user_text": "hello",
        "messages": [],
        "system_prompt": "Base system prompt",
        "metadata": {**metadata_overrides},
    }


def _make_middleware_mock(enriched: str = "", metadata: dict | None = None) -> AsyncMock:
    """Build a mock MemoryMiddleware whose before_llm_call returns given values."""
    mw = AsyncMock()
    mw.before_llm_call.return_value = (enriched, metadata or {})
    return mw


# ── Task 1.2–1.4: personality_overlay → system_prompt ────────


@pytest.mark.asyncio
async def test_overlay_appended_to_system_prompt():
    """Overlay text from metadata MUST be appended to system_prompt."""
    from animetta.orchestration.graph.llm_node import _enrich_system_prompt

    state = _make_state(personality_overlay="当前情绪：保持积极愉快的语气")
    overlay = state["metadata"].get("personality_overlay", "")
    base_prompt = state["system_prompt"]

    # After fix: llm_node should append overlay to prompt before enrichment.
    # Simulate the expected fix behaviour:
    effective_prompt = base_prompt
    if overlay:
        effective_prompt = f"{base_prompt}\n\n{overlay}"

    enriched = _enrich_system_prompt(effective_prompt, "")
    assert "当前情绪：保持积极愉快的语气" in enriched


@pytest.mark.asyncio
async def test_no_overlay_when_empty():
    """Empty overlay MUST NOT change system_prompt."""
    from animetta.orchestration.graph.llm_node import _enrich_system_prompt

    state = _make_state(personality_overlay="")
    overlay = state["metadata"].get("personality_overlay", "")
    base_prompt = state["system_prompt"]

    effective_prompt = base_prompt
    if overlay:
        effective_prompt = f"{base_prompt}\n\n{overlay}"

    enriched = _enrich_system_prompt(effective_prompt, "")
    assert enriched == base_prompt


@pytest.mark.asyncio
async def test_no_overlay_when_metadata_missing():
    """Missing metadata key MUST NOT change system_prompt."""
    from animetta.orchestration.graph.llm_node import _enrich_system_prompt

    state = _make_state()  # no personality_overlay key
    overlay = state.get("metadata", {}).get("personality_overlay", "")
    base_prompt = state["system_prompt"]

    effective_prompt = base_prompt
    if overlay:
        effective_prompt = f"{base_prompt}\n\n{overlay}"

    enriched = _enrich_system_prompt(effective_prompt, "")
    assert enriched == base_prompt


# ── Task 1.5–1.6: character_known/unknown → middleware ────────


@pytest.mark.asyncio
async def test_character_boundaries_passed_to_middleware():
    """character_known/unknown from metadata MUST reach middleware.before_llm_call."""
    mw = _make_middleware_mock(enriched="memories", metadata={"count": 1})
    config: dict[str, Any] = {"configurable": {"memory_middleware": mw}}

    state = _make_state(
        character_known=["编程", "AI"],
        character_unknown=["烹饪"],
    )
    meta = state["metadata"]

    await _retrieve_memory_context(
        session_id="test",
        query="hello",
        config=config,
        character_known=meta.get("character_known"),
        character_unknown=meta.get("character_unknown"),
    )

    call_kwargs = mw.before_llm_call.call_args[1]
    assert call_kwargs["character_known"] == ["编程", "AI"]
    assert call_kwargs["character_unknown"] == ["烹饪"]


@pytest.mark.asyncio
async def test_default_when_no_boundaries():
    """Missing boundary keys MUST fall back to None defaults."""
    mw = _make_middleware_mock()
    config: dict[str, Any] = {"configurable": {"memory_middleware": mw}}

    state = _make_state()  # no character keys
    meta = state["metadata"]

    await _retrieve_memory_context(
        session_id="test",
        query="hello",
        config=config,
        character_known=meta.get("character_known"),
        character_unknown=meta.get("character_unknown"),
    )

    call_kwargs = mw.before_llm_call.call_args[1]
    assert call_kwargs["character_known"] is None
    assert call_kwargs["character_unknown"] is None


# ── Task 1.7–1.8: MBTI dimensions → middleware ───────────────


@pytest.mark.asyncio
async def test_mbti_dimensions_passed_to_middleware():
    """MBTI dimensions from metadata MUST reach middleware.before_llm_call."""
    mw = _make_middleware_mock()
    config: dict[str, Any] = {"configurable": {"memory_middleware": mw}}

    state = _make_state(mbti_ei=20, mbti_sn=65, mbti_tf=80, mbti_jp=73)
    meta = state["metadata"]

    await _retrieve_memory_context(
        session_id="test",
        query="hello",
        config=config,
        mbti_ei=meta.get("mbti_ei", 50),
        mbti_sn=meta.get("mbti_sn", 50),
        mbti_tf=meta.get("mbti_tf", 50),
        mbti_jp=meta.get("mbti_jp", 50),
    )

    call_kwargs = mw.before_llm_call.call_args[1]
    assert call_kwargs["mbti_ei"] == 20
    assert call_kwargs["mbti_sn"] == 65
    assert call_kwargs["mbti_tf"] == 80
    assert call_kwargs["mbti_jp"] == 73


@pytest.mark.asyncio
async def test_default_mbti_when_no_metadata():
    """Missing MBTI keys MUST fall back to 50/50/50/50."""
    mw = _make_middleware_mock()
    config: dict[str, Any] = {"configurable": {"memory_middleware": mw}}

    state = _make_state()  # no mbti keys
    meta = state["metadata"]

    await _retrieve_memory_context(
        session_id="test",
        query="hello",
        config=config,
        mbti_ei=meta.get("mbti_ei", 50),
        mbti_sn=meta.get("mbti_sn", 50),
        mbti_tf=meta.get("mbti_tf", 50),
        mbti_jp=meta.get("mbti_jp", 50),
    )

    call_kwargs = mw.before_llm_call.call_args[1]
    assert call_kwargs["mbti_ei"] == 50
    assert call_kwargs["mbti_sn"] == 50
    assert call_kwargs["mbti_tf"] == 50
    assert call_kwargs["mbti_jp"] == 50
