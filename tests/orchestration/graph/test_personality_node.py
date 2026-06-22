from __future__ import annotations

"""Tests for personality node — mode/mood detection and overlay prompt."""

import pytest

from animetta.orchestration.graph.personality_node import personality_node
from animetta.orchestration.graph.state import create_initial_state


class TestPersonalityNode:
    """Personality node: determines mode and mood from state/metadata."""

    @pytest.mark.asyncio
    async def test_default_mode(self):
        """Non-bilibili channel yields 'default' mode and no streaming overlay."""

        state = create_initial_state(
            session_id="test",
            channel_id="web",
        )
        result = await personality_node(state)

        assert result["personality_mode"] == "default"
        # No mood set by default
        assert result["personality_mood"] is None
        # No overlay for default mode without mood
        overlay = result["metadata"].get("personality_overlay", "")
        assert overlay == ""

    @pytest.mark.asyncio
    async def test_streaming_mode_for_bilibili(self):
        """Bilibili channel triggers 'streaming' mode with Chinese overlay."""

        state = create_initial_state(
            session_id="test",
            channel_id="bilibili_live",
        )
        result = await personality_node(state)

        assert result["personality_mode"] == "streaming"
        overlay = result["metadata"].get("personality_overlay", "")
        assert "直播模式" in overlay
        assert "弹幕互动" in overlay

    @pytest.mark.asyncio
    async def test_case_insensitive_bilibili_check(self):
        """Channel matching for bilibili is case-insensitive."""

        state = create_initial_state(
            session_id="test",
            channel_id="BILIBILI_ROOM",
        )
        result = await personality_node(state)
        assert result["personality_mode"] == "streaming"

    @pytest.mark.asyncio
    async def test_mood_from_state_emotion(self):
        """Mood is set from state['emotion'] when present in MOOD_ORDER."""

        state = create_initial_state(session_id="test")
        state["emotion"] = "happy"
        result = await personality_node(state)

        assert result["personality_mood"] == "happy"
        overlay = result["metadata"].get("personality_overlay", "")
        assert "积极愉快" in overlay

    @pytest.mark.asyncio
    async def test_mood_from_metadata_emotion(self):
        """Mood falls back to metadata.emotion when state.emotion is absent."""

        state = create_initial_state(
            session_id="test",
        )
        state["metadata"] = {"emotion": "sad"}
        result = await personality_node(state)

        assert result["personality_mood"] == "sad"
        overlay = result["metadata"].get("personality_overlay", "")
        assert "温和" in overlay

    @pytest.mark.asyncio
    async def test_mood_state_takes_priority_over_metadata(self):
        """state.emotion overrides metadata.emotion."""

        state = create_initial_state(session_id="test")
        state["emotion"] = "angry"
        state["metadata"] = {"emotion": "happy"}
        result = await personality_node(state)

        # state.emotion wins
        assert result["personality_mood"] == "angry"
        overlay = result["metadata"].get("personality_overlay", "")
        assert "冷静理性" in overlay

    @pytest.mark.asyncio
    async def test_unknown_emotion_falls_back_to_existing_mood(self):
        """Emotion not in MOOD_ORDER keeps the existing personality_mood."""

        state = create_initial_state(session_id="test")
        state["personality_mood"] = "happy"
        state["emotion"] = "confused"  # not in MOOD_ORDER
        result = await personality_node(state)

        assert result["personality_mood"] == "happy"

    @pytest.mark.asyncio
    async def test_all_mood_descriptions(self):
        """Each mood in MOOD_ORDER produces a Chinese description."""

        for mood in ["neutral", "thinking", "surprised", "sad", "angry", "happy"]:
            state = create_initial_state(session_id="test")
            state["emotion"] = mood
            result = await personality_node(state)
            assert result["personality_mood"] == mood
            assert result["metadata"].get("personality_overlay", "") != ""

    @pytest.mark.asyncio
    async def test_streaming_plus_mood_produces_combined_overlay(self):
        """Both streaming mode and mood contribute to overlay."""

        state = create_initial_state(
            session_id="test",
            channel_id="bilibili",
        )
        state["emotion"] = "surprised"
        result = await personality_node(state)

        assert result["personality_mode"] == "streaming"
        assert result["personality_mood"] == "surprised"
        overlay = result["metadata"].get("personality_overlay", "")
        assert "直播模式" in overlay
        assert "惊讶" in overlay

    @pytest.mark.asyncio
    async def test_metadata_is_merged_with_personality_keys(self):
        """Returned metadata includes personality_overlay, personality_mode, personality_mood."""

        state = create_initial_state(
            session_id="test",
            channel_id="bilibili",
        )
        state["metadata"] = {"custom_key": "val"}
        result = await personality_node(state)

        meta = result["metadata"]
        assert meta["custom_key"] == "val"
        assert "personality_overlay" in meta
        assert "personality_mode" in meta
        assert "personality_mood" in meta
        assert meta["personality_mode"] == "streaming"

    @pytest.mark.asyncio
    async def test_missing_metadata_handled_gracefully(self):
        """State without metadata key should not crash."""

        state = create_initial_state(session_id="test")
        state.pop("metadata", None)
        result = await personality_node(state)

        # Should survive missing metadata and produce sensible defaults
        assert result["personality_mode"] == "default"
        assert result["personality_mood"] is None

    @pytest.mark.asyncio
    async def test_missing_channel_id_defaults_to_default_mode(self):
        """State without channel_id defaults to 'default' mode."""

        state = create_initial_state(session_id="test")
        state.pop("channel_id", None)
        result = await personality_node(state)

        assert result["personality_mode"] == "default"

    @pytest.mark.asyncio
    async def test_missing_emotion_leaves_mood_unchanged(self):
        """When no emotion in state or metadata, keep the current mood."""

        state = create_initial_state(session_id="test")
        state["personality_mood"] = "happy"
        # no emotion set
        result = await personality_node(state)

        assert result["personality_mood"] == "happy"
