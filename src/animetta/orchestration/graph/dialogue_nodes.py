"""Thin LangGraph nodes for the isolated two-pass golden dialogue."""

import time
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.services.dialogue import AnimaComposer, DialogueServiceError, Reasoner
from animetta.services.dialogue.contracts import ComposerResult, ReasonerResult
from animetta.services.dialogue.guard import select_final_response
from animetta.services.dialogue.models import ComposerRequest, ReasonerRequest

from .conversation_session import ConversationSessionState
from .persistence_policy import PersistenceMode, PersistenceRequest, decide_persistence
from .state import AgentState, log_timing
from .subtitle_translator import strip_runtime_markers


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    return config.get("configurable", {}) if config else {}


def _session(config: RunnableConfig | None) -> ConversationSessionState:
    session = _configurable(config).get("conversation_session")
    return session if isinstance(session, ConversationSessionState) else ConversationSessionState()


def _llm(config: RunnableConfig | None) -> Any:
    context = _configurable(config).get("service_context")
    llm = getattr(context, "llm_engine", None)
    if llm is None:
        raise DialogueServiceError("service_unavailable")
    return llm


def _memory_mode(config: RunnableConfig | None) -> PersistenceMode:
    context = _configurable(config).get("service_context")
    system = getattr(getattr(context, "config", None), "system", None)
    mode = getattr(system, "long_term_memory_mode", "off")
    return cast(PersistenceMode, mode) if mode in {"off", "read_only", "read_write"} else "off"


async def reasoner_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    metadata = state.get("metadata", {})
    if metadata.get("is_inspection") or metadata.get("is_probe"):
        return {"turn_scratch": {}, "metadata": {**metadata, "dialogue_status": "filtered_probe"}}
    session = _session(config)
    request = ReasonerRequest(
        user_input=state.get("user_text", ""),
        persona_prompt=state.get("system_prompt") or "",
        completed_window=session.completed_window,
        roleplay_correction=str(metadata.get("roleplay_correction", "")),
    )
    try:
        started = time.perf_counter()
        result = await Reasoner(_llm(config)).reason(request)
    except DialogueServiceError as exc:
        logger.warning(f"[{state.get('session_id', 'unknown')}] Reasoner failed: {exc.code}")
        return {
            "turn_scratch": {},
            "error": "reasoner_failed",
            "metadata": {
                **metadata,
                "dialogue_status": "reasoner_failed",
                "reasoner_error": exc.code,
            },
        }
    log_timing(state, "reasoner.api_call", (time.perf_counter() - started) * 1000)
    provider = type(_llm(config)).__name__
    return {
        "turn_scratch": {"reasoner": result},
        "metadata": {
            **metadata,
            "dialogue_status": "reasoner_ready",
            "reasoner_provider": provider,
        },
    }


async def anima_composer_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    scratch = dict(state.get("turn_scratch", {}))
    reasoner = scratch.get("reasoner")
    if not isinstance(reasoner, ReasonerResult):
        return {"turn_scratch": scratch}
    session = _session(config)
    request = ComposerRequest(
        user_input=state.get("user_text", ""),
        persona_prompt=state.get("system_prompt") or "",
        reasoner=reasoner,
        completed_window=session.completed_window,
        mood=session.mood,
        fatigue=session.fatigue,
        affinity=session.affinity,
        roleplay_correction=str(state.get("metadata", {}).get("roleplay_correction", "")),
    )
    try:
        started = time.perf_counter()
        scratch["composer"] = await AnimaComposer(_llm(config)).compose(request)
    except DialogueServiceError as exc:
        scratch["composer_error"] = exc.code
    log_timing(state, "composer.api_call", (time.perf_counter() - started) * 1000)
    return {
        "turn_scratch": scratch,
        "metadata": {
            **state.get("metadata", {}),
            "composer_provider": type(_llm(config)).__name__,
        },
    }


async def response_guard_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    del config
    scratch = dict(state.get("turn_scratch", {}))
    reasoner = scratch.get("reasoner")
    if not isinstance(reasoner, ReasonerResult):
        return {"response_text": "", "response_chunks": [], "turn_scratch": scratch}
    composer = scratch.get("composer")
    selection = select_final_response(
        reasoner,
        composer if isinstance(composer, ComposerResult) else None,
        rejection_code=scratch.get("composer_error"),
    )
    scratch["selection_source"] = selection.source
    if selection.rejection_code:
        scratch["rejection_code"] = selection.rejection_code
    visible_text = strip_runtime_markers(selection.text)
    return {
        "response_text": visible_text,
        "response_chunks": [selection.text],
        "turn_scratch": scratch,
        "metadata": {
            **state.get("metadata", {}),
            "dialogue_status": selection.source,
            "composer_rejection": selection.rejection_code,
        },
    }


async def conversation_finalizer_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Commit one eligible final pair and always destroy authored scratch."""
    scratch = state.get("turn_scratch", {})
    metadata = state.get("metadata", {})
    response = state.get("response_text", "")
    task_id = state.get("task_id") or ""
    eligible = (
        bool(response.strip())
        and not state.get("error")
        and not metadata.get("is_inspection")
        and not metadata.get("is_probe")
        and metadata.get("dialogue_status") in {"composer", "composer_fallback"}
    )
    policy = decide_persistence(
        PersistenceRequest(
            mode=_memory_mode(config),
            sink="session_window",
            content_class="selected_final" if eligible else "incomplete",
            completed=eligible,
            real_provider=eligible,
        )
    )
    committed = False
    if policy.allowed:
        composer = scratch.get("composer")
        committed = _session(config).commit(
            task_id=task_id,
            user_text=state.get("user_text", ""),
            final_response=response,
            mood=composer.mood if isinstance(composer, ComposerResult) else None,
            affinity_delta=(composer.affinity_delta if isinstance(composer, ComposerResult) else 0),
        )
    if committed:
        await _persist_selected_final(state, config)
    return {
        "turn_scratch": {},
        "metadata": {**metadata, "conversation_committed": committed},
    }


async def _persist_selected_final(state: AgentState, config: RunnableConfig | None) -> None:
    decision = decide_persistence(
        PersistenceRequest(
            mode=_memory_mode(config),
            sink="long_term_write",
            content_class="selected_final",
            completed=True,
            real_provider=True,
        )
    )
    if not decision.allowed:
        return
    context = _configurable(config).get("service_context")
    memory = getattr(context, "memory_system", None)
    if memory is None:
        return
    try:
        await memory.encode(
            user_input=state.get("user_text", ""),
            agent_response=state.get("response_text", ""),
            emotion_vad=None,
            session_id=state.get("session_id", "unknown"),
        )
    except Exception:
        # Memory is non-critical and content must never enter an error log.
        return
