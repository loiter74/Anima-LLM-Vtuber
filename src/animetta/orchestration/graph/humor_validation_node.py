"""Graph-visible Humor Agent candidate validation node."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import RunnableConfig
from loguru import logger

from animetta.services.humor.filters import validate_humor_candidate
from animetta.services.humor.history_safe import replace_last_assistant_history
from animetta.services.humor.metadata import (
    candidate_from_metadata,
    record_humor_validation,
)

from .humor_utils import get_service_context, resolve_humor_config
from .state import AgentState


async def humor_validation_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Validate an internal humor candidate and finalize the direct assistant reply."""
    session_id = state.get("session_id", "unknown")
    normal_response = state.get("response_text", "")
    response_chunks = state.get("response_chunks", [])
    metadata = {**state.get("metadata", {})}

    service_context = get_service_context(config)
    humor_config = resolve_humor_config(config, service_context)
    candidate = candidate_from_metadata(metadata)

    final_response = normal_response
    final_chunks = response_chunks

    if candidate is not None:
        rejection = validate_humor_candidate(candidate, humor_config)
        if rejection:
            candidate.reject(rejection)
            logger.debug(
                f"[{session_id}] [HumorValidationNode] Rejected: {rejection}"
            )
        else:
            candidate.accept()
            final_response = candidate.visible_response
            final_chunks = [final_response]
            llm_engine = getattr(service_context, "llm_engine", None) if service_context else None
            if llm_engine:
                replace_last_assistant_history(
                    llm_engine,
                    candidate.normal_response,
                    final_response,
                )
            logger.info(f"[{session_id}] [HumorValidationNode] Accepted humorous rewrite")
        metadata = record_humor_validation(metadata, candidate)

    return {
        "response_text": final_response,
        "response_chunks": final_chunks,
        "messages": [AIMessage(content=final_response)],
        "metadata": metadata,
    }
