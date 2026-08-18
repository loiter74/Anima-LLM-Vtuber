"""Graph-visible Humor Agent candidate generation node."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.services.bilibili.response_policy import is_proactive_topic_turn
from animetta.services.humor import HumorAgent, HumorRewriteRequest
from animetta.services.humor.metadata import record_humor_candidate
from animetta.services.scene_analysis.validation import validate_scene_guidance

from .humor_utils import get_service_context, resolve_humor_config
from .state import AgentState


async def humor_rewrite_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Generate an internal humor candidate without replacing the visible reply."""
    session_id = state.get("session_id", "unknown")
    normal_response = state.get("response_text", "")
    response_chunks = state.get("response_chunks", [])
    metadata = {**state.get("metadata", {})}

    scene_guidance, _ = validate_scene_guidance(metadata.get("scene_guidance"))
    if is_proactive_topic_turn(metadata) or scene_guidance is not None:
        return {
            "response_text": normal_response,
            "response_chunks": response_chunks,
            "metadata": metadata,
        }

    service_context = get_service_context(config)
    humor_config = resolve_humor_config(config, service_context)
    if not humor_config.enabled:
        return {
            "response_text": normal_response,
            "response_chunks": response_chunks,
            "metadata": metadata,
        }

    llm_engine = getattr(service_context, "llm_engine", None) if service_context else None
    if not llm_engine:
        logger.debug(f"[{session_id}] [HumorRewriteNode] LLM engine not available")
        return {
            "response_text": normal_response,
            "response_chunks": response_chunks,
            "metadata": metadata,
        }

    request = HumorRewriteRequest(
        user_input=state.get("user_text", ""),
        normal_response=normal_response,
        persona=state.get("persona") or {},
        metadata=metadata,
        config=humor_config,
    )
    result = await HumorAgent(llm_engine, humor_config).generate_candidate(request)
    metadata = record_humor_candidate(metadata, result)

    return {
        "response_text": normal_response,
        "response_chunks": response_chunks,
        "metadata": metadata,
    }
