"""Build PromptContext from AgentState and config."""

from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig

from animetta.services.bilibili.response_policy import is_proactive_topic_turn
from animetta.services.runtime_config import build_runtime_system_prompt
from animetta.services.scene_analysis.validation import validate_scene_guidance

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
    service_context = _get_service_context(config)
    base_system_prompt, base_warnings = _build_base_system_prompt(state, service_context)
    scene_guidance, scene_warnings = validate_scene_guidance(metadata.get("scene_guidance"))
    proactive = is_proactive_topic_turn(metadata)
    seed = metadata.get("proactive_topic_seed")
    recent = metadata.get("proactive_recent_outputs")
    max_chars = metadata.get("proactive_topic_max_chars", 36)
    return PromptContext(
        session_id=state.get("session_id", "unknown"),
        base_system_prompt=base_system_prompt,
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
            getattr(service_context, "runtime_config_version", state.get("config_version", 1)),
        ),
        base_system_prompt_warnings=base_warnings,
        scene_guidance=scene_guidance,
        scene_guidance_warnings=scene_warnings,
        available_tool_names=_available_tool_names(config),
        actor_role=metadata.get("actor_role"),
        source=metadata.get("source"),
        audience=metadata.get("audience"),
        has_private_developer_context=bool(metadata.get("has_private_developer_context")),
        is_proactive_topic=proactive,
        proactive_topic_seed=(dict(seed) if proactive and isinstance(seed, dict) else None),
        proactive_recent_outputs=(
            tuple(str(item) for item in recent[:8])
            if proactive and isinstance(recent, list)
            else ()
        ),
        proactive_topic_max_chars=(
            int(max_chars) if proactive and isinstance(max_chars, int) else 36
        ),
    )


def _available_tool_names(config: RunnableConfig | None) -> frozenset[str]:
    if not config:
        return frozenset()
    configurable = (
        config.get("configurable") or {}
        if isinstance(config, dict)
        else getattr(config, "configurable", {}) or {}
    )
    tools_map = (
        configurable.get("tools_map")
        if isinstance(configurable, dict)
        else getattr(configurable, "tools_map", None)
    )
    return (
        frozenset(str(name) for name in tools_map) if isinstance(tools_map, dict) else frozenset()
    )


def _get_service_context(config: RunnableConfig | None) -> Any | None:
    """Extract the active ServiceContext from a LangGraph RunnableConfig."""
    if not config:
        return None

    if isinstance(config, dict):
        configurable = config.get("configurable") or {}
    else:
        configurable = getattr(config, "configurable", {}) or {}

    if isinstance(configurable, dict):
        return configurable.get("service_context")
    return getattr(configurable, "service_context", None)


def _build_base_system_prompt(
    state: dict[str, Any],
    service_context: Any | None,
) -> tuple[str, list[str]]:
    """Build persona prompt from active runtime config with state fallback."""
    active_config = getattr(service_context, "config", None)
    if active_config is not None:
        runtime_prompt = build_runtime_system_prompt(active_config)
        if runtime_prompt.system_prompt:
            return runtime_prompt.system_prompt, runtime_prompt.warnings
        return state.get("system_prompt") or "", runtime_prompt.warnings
    return state.get("system_prompt") or "", []
