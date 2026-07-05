"""Build PromptContext from AgentState and config."""

from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig

from .types import PromptContext


def build_context(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
    memory_context: str = "",
    memory_metadata: dict[str, Any] | None = None,
) -> PromptContext:
    """Extract prompt-relevant data from state and config into a PromptContext.

    Does not modify state or config.
    """
    metadata = state.get("metadata", {})
    return PromptContext(
        session_id=state.get("session_id", "unknown"),
        base_system_prompt=state.get("system_prompt") or "",
        personality_overlay=metadata.get("personality_overlay", ""),
        personality_mode=metadata.get("personality_mode", "default"),
        personality_mood=metadata.get("personality_mood"),
        memory_context=memory_context,
        memory_metadata=memory_metadata or {},
        character_known=metadata.get("character_known") or [],
        character_unknown=metadata.get("character_unknown") or [],
        mbti_ei=metadata.get("mbti_ei", 50),
        mbti_sn=metadata.get("mbti_sn", 50),
        mbti_tf=metadata.get("mbti_tf", 50),
        mbti_jp=metadata.get("mbti_jp", 50),
        roleplay_correction=metadata.get("roleplay_correction", ""),
        # Affinity: prefer metadata (cross-turn overlay path), fall back to
        # top-level state (set by create_initial_state on the first turn).
        affinity=metadata.get(
            "affinity",
            state.get("affinity", 50),
        ),
        config_version=metadata.get(
            "config_version",
            state.get("config_version", 1),
        ),
    )
