"""Tests for emotion analyzer switching and raw-text reading.

Verifies:
1. emotion_node reads response_chunks (raw with tags) instead of response_text (stripped)
2. StandaloneLLMTagAnalyzer correctly parses [emotion] tags from LLM output
"""

from __future__ import annotations

from typing import Any

import pytest

from animetta.avatar.analyzers.llm_tag import StandaloneLLMTagAnalyzer

# ── StandaloneLLMTagAnalyzer contract tests ────────────────


@pytest.mark.parametrize(
    "text, expected_primary",
    [
        ("数据不支持你的结论。[neutral]", "neutral"),
        ("这个请求不在我的训练数据里——但我可以试试。[thinking]", "thinking"),
        ("你好呀！[happy]", "happy"),
        ("今天的代码写得我好难过。[sad]", "sad"),
        ("你竟然删了整个数据库？[angry]", "angry"),
        ("哇你真的做到了！[surprised]", "surprised"),
    ],
)
def test_llm_tag_extracts_emotion_from_persona_output(text, expected_primary):
    """Analyzer MUST parse [emotion] tags from persona-style output."""
    analyzer = StandaloneLLMTagAnalyzer(
        valid_emotions=["happy", "sad", "angry", "surprised", "neutral", "thinking"]
    )
    result = analyzer.extract(text)
    assert result.primary == expected_primary
    assert result.confidence > 0


def test_llm_tag_returns_neutral_when_no_tags():
    """Text without [emotion] tags MUST return neutral."""
    analyzer = StandaloneLLMTagAnalyzer()
    result = analyzer.extract("这是一段没有任何情绪标签的普通文本")
    assert result.primary == "neutral"
    assert result.confidence == 0.0


def test_llm_tag_ignores_invalid_emotion():
    """Invalid emotion tags (not in valid_emotions) MUST be ignored."""
    analyzer = StandaloneLLMTagAnalyzer(valid_emotions=["happy", "neutral"])
    result = analyzer.extract("Hello [confused] world [happy]")
    assert result.primary == "happy"


# ── emotion_node reads raw chunks ──────────────────────────


@pytest.mark.asyncio
async def test_emotion_node_reads_response_chunks_raw_text():
    """emotion_node MUST read response_chunks (raw) not response_text (stripped)."""
    from animetta.orchestration.graph.emotion_node import emotion_node

    analyzer = StandaloneLLMTagAnalyzer(
        valid_emotions=["happy", "sad", "angry", "surprised", "neutral", "thinking"]
    )

    state: dict[str, Any] = {
        "session_id": "test",
        # response_text is already stripped by llm_node
        "response_text": "数据不支持你的结论。",
        # response_chunks preserves raw text with tags
        "response_chunks": ["数据不支持你的结论。[neutral]"],
    }

    config: dict[str, Any] = {
        "configurable": {
            "emotion_analyzer": analyzer,
        }
    }

    result = await emotion_node(state, config)
    assert result["emotion"] == "neutral"


@pytest.mark.asyncio
async def test_emotion_node_falls_back_to_response_text_when_no_chunks():
    """When response_chunks is empty, emotion_node MUST fall back to response_text."""
    from animetta.orchestration.graph.emotion_node import emotion_node

    analyzer = StandaloneLLMTagAnalyzer(
        valid_emotions=["happy", "sad", "angry", "surprised", "neutral", "thinking"]
    )

    state: dict[str, Any] = {
        "session_id": "test",
        "response_text": "你好呀！[happy]",  # tags still here (edge case)
        "response_chunks": [],               # empty chunks
    }

    config: dict[str, Any] = {
        "configurable": {
            "emotion_analyzer": analyzer,
        }
    }

    result = await emotion_node(state, config)
    assert result["emotion"] == "happy"


@pytest.mark.asyncio
async def test_emotion_node_falls_back_to_neutral_when_no_text():
    """No text at all MUST return neutral."""
    from animetta.orchestration.graph.emotion_node import emotion_node

    analyzer = StandaloneLLMTagAnalyzer()

    state: dict[str, Any] = {
        "session_id": "test",
        "response_text": "",
        "response_chunks": [],
    }

    config: dict[str, Any] = {
        "configurable": {
            "emotion_analyzer": analyzer,
        }
    }

    result = await emotion_node(state, config)
    assert result["emotion"] == "neutral"
