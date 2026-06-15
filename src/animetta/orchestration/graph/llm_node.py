"""LLM inference node - supports tool calls and streaming output"""

import asyncio
import re
import time as time_module
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import RunnableConfig
from loguru import logger

from animetta.tracing.metrics import get_rag_chunks, get_rag_duration, get_rag_top_score

from .interrupt_handler import get_interrupt_handler
from .memory_middleware import MemoryMiddleware
from .node_error import log_node_error
from .state import AgentState, log_timing

# Configurable timeout for LLM provider calls (default: 30 seconds)
TIMEOUT_SECONDS = 30
FALLBACK_RESPONSE = "I need a moment to think about that."

# Regex for emotion tags like [happy], [neutral], [sad]
_EMOTION_TAG_RE = re.compile(r"\s*\[[\w-]+\]\s*")


def _strip_emotion_tags(text: str) -> str:
    """Remove emotion tags like [happy], [neutral] from LLM output."""
    return _EMOTION_TAG_RE.sub(" ", text).strip()

# ========================================
# RAG memory retrieval helper functions
# ========================================

def _get_memory_system(config: RunnableConfig | None) -> Any | None:
    """Get memory_system from LangGraph config"""
    if config:
        service_context = config.get("configurable", {}).get("service_context")
        if service_context and hasattr(service_context, "memory_system"):
            return service_context.memory_system
    return None


def _get_memory_middleware(config: RunnableConfig | None) -> MemoryMiddleware | None:
    """Get or create MemoryMiddleware from LangGraph config"""
    if config:
        configurable = config.get("configurable", {})
        # Explicit None means "skip middleware" (used in tests)
        if "memory_middleware" in configurable:
            return configurable["memory_middleware"]
        memory_system = _get_memory_system(config)
        if memory_system:
            middleware = MemoryMiddleware(memory_system=memory_system)
            return middleware
    return None


async def _retrieve_memory_context(
    session_id: str,
    query: str,
    config: RunnableConfig | None,
    max_turns: int = 5,
    current_emotion: Any = None,
) -> tuple[str, dict]:
    """
    Retrieve memory context via LivingMemorySystem V2 recall().

    Args:
        session_id: Session ID
        query: Query text (user input)
        config: LangGraph config
        max_turns: Maximum number of turns to retrieve
        current_emotion: VADVector for mood-congruent recall

    Returns:
        Tuple of (enriched system prompt, metadata dict)
    """
    middleware = _get_memory_middleware(config)
    if not middleware:
        logger.debug(f"[{session_id}] [LLMNode] MemoryMiddleware not available, skipping RAG")
        return "", {}

    try:
        enriched, metadata = await middleware.before_llm_call(
            session_id=session_id,
            user_input=query,
            current_emotion=current_emotion,
        )
        if metadata:
            logger.info(f"[{session_id}] [LLMNode] Memory injected")
        return enriched, metadata or {}
    except Exception as e:
        logger.warning(f"[{session_id}] [LLMNode] MemoryMiddleware retrieval failed: {e}")
        return "", {}


def _enrich_system_prompt(
    base_prompt: str | None,
    memory_context: str,
) -> str:
    """
    Inject memory context into the system prompt

    Note: When MemoryMiddleware is active, memory_context is already
    a fully-enriched prompt. This function is kept for backward compatibility.

    Args:
        base_prompt: Base system prompt
        memory_context: Memory context / enriched prompt text

    Returns:
        Enriched system prompt
    """
    if not memory_context:
        return base_prompt or ""
    if not base_prompt:
        return memory_context

    parts = [base_prompt, memory_context]
    return "\n\n---\n\n".join(parts)


def _get_service_context(config: RunnableConfig | None) -> Any | None:
    """Get service_context from LangGraph config"""
    if config:
        return config.get("configurable", {}).get("service_context")
    return None


def _get_config_value(config: RunnableConfig | None, key: str, default: Any = None) -> Any:
    """Get config value from LangGraph config"""
    if config:
        return config.get("configurable", {}).get(key, default)
    return default


def _notify_middleware_after(
    session_id: str,
    user_input: str,
    response: str,
    config: RunnableConfig | None,
) -> None:
    """Non-blocking notification to middleware that LLM call is complete."""
    try:
        import asyncio
        middleware = _get_memory_middleware(config)
        if middleware:
            asyncio.ensure_future(
                middleware.after_llm_call(
                    session_id=session_id,
                    user_input=user_input,
                    agent_response=response,
                )
            )
    except Exception as e:
        logger.debug(f"[{session_id}] [LLMNode] middleware after_llm_call notification failed: {e}")


async def llm_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    LLM inference node

    Input: state["user_text"], state["messages"], state["persona"]
    Output: state["messages"], state["response_text"], state["response_chunks"], state["tool_calls"]
    """
    session_id = state.get("session_id", "unknown")
    user_text = state.get("user_text", "")
    list(state.get("messages", []))

    logger.info(f"[{session_id}] [LLMNode] Processing...")

    # Validate input
    if not user_text:
        logger.warning(f"[{session_id}] [LLMNode] No user text, skipping")
        return {"error": "No user text", "response_text": "", "response_chunks": [], "tool_calls": None}

    service_context = _get_service_context(config)
    if not service_context:
        logger.error(f"[{session_id}] [LLMNode] service_context not configured")
        await log_node_error(session_id, "llm_node", "invalid_response", duration_ms=0)
        return {"error": "service_context not configured", "response_text": "", "response_chunks": [], "tool_calls": None}

    llm_engine = service_context.llm_engine
    if not llm_engine:
        logger.error(f"[{session_id}] [LLMNode] LLM engine not initialized")
        await log_node_error(session_id, "llm_node", "invalid_response", duration_ms=0)
        return {"error": "LLM engine not initialized", "response_text": "", "response_chunks": [], "tool_calls": None}

    # RAG: retrieve via LivingMemorySystem V2 recall()
    vad_tuple = state.get("emotion_vad")
    from animetta.memory.v2.emotion_field import VADVector
    current_emotion = VADVector(*vad_tuple) if vad_tuple else None
    t_rag = time_module.perf_counter()
    retrieval_result = await _retrieve_memory_context(
        session_id=session_id,
        query=user_text,
        config=config,
        max_turns=5,
        current_emotion=current_emotion,
    )
    memory_context, rag_metadata = retrieval_result if isinstance(retrieval_result, tuple) else (retrieval_result, {})
    rag_duration = (time_module.perf_counter() - t_rag) * 1000
    log_timing(state, "llm.rag_retrieval", rag_duration, f"query='{user_text[:50]}'")

    # OTel metrics: RAG retrieval duration + chunk count + top score
    try:
        rd = get_rag_duration()
        if rd is not None:
            rd.record(rag_duration / 1000.0, {"strategy": "hybrid"})
        rc = get_rag_chunks()
        if rc is not None:
            chunk_count = rag_metadata.get("memory_count", rag_metadata.get("fuzzy_count", 0))
            if chunk_count > 0:
                rc.record(chunk_count, {"strategy": "hybrid"})
        rts = get_rag_top_score()
        if rts is not None:
            top_score = rag_metadata.get("top_score", 0.0)
            if top_score > 0:
                rts.record(top_score, {"strategy": "hybrid"})
    except Exception as e:
        logger.warning(f"[{session_id}] [LLMNode] OTel RAG metrics recording failed: {e}")

    # Check if tools are enabled
    enable_tools = _get_config_value(config, "enable_tools", False)
    chat_model = _get_config_value(config, "chat_model", None)

    if enable_tools and chat_model:
        return await _llm_with_tools(session_id, state, service_context, chat_model, config, memory_context)
    else:
        return await _llm_without_tools(session_id, state, service_context, config, memory_context)


async def _llm_with_tools(
    session_id: str,
    state: AgentState,
    service_context: Any,
    chat_model: Any,
    config: RunnableConfig | None = None,
    memory_context: str = "",
) -> dict[str, Any]:
    """Use tool calling mode"""
    user_text = state.get("user_text", "")
    messages = list(state.get("messages", []))
    llm_engine = service_context.llm_engine

    logger.info(f"[{session_id}] [LLMNode] Using tool calling mode")

    system_prompt = state.get("system_prompt")
    if not system_prompt and service_context.config:
        system_prompt = service_context.config.get_system_prompt()

    # Inject memory into system_prompt
    enriched_prompt = _enrich_system_prompt(system_prompt, memory_context)

    bound_tools = getattr(chat_model, "bound_tools", []) or getattr(chat_model, "tools", [])

    history_for_llm = [msg for msg in messages if isinstance(msg, (HumanMessage, AIMessage, ToolMessage))]

    try:
        t_llm = time_module.perf_counter()
        response = await llm_engine.chat_with_tools(
            user_text,
            tools=bound_tools,
            langchain_history=history_for_llm,
            system_prompt=enriched_prompt,  # Use enriched prompt
        )
        llm_duration = (time_module.perf_counter() - t_llm) * 1000
        log_timing(state, "llm.api_call", llm_duration, "chat_with_tools")

        if isinstance(response, dict):
            if response.get("tool_calls"):
                tool_calls = response["tool_calls"]
                formatted_tool_calls = [
                    {"id": tc.get("id", ""), "name": tc.get("name", ""), "args": tc.get("args", {})}
                    for tc in tool_calls
                ]

                ai_message = AIMessage(content=_strip_emotion_tags(response.get("content", "") or "Calling tools..."), tool_calls=tool_calls)

                # after_llm_call notification (non-blocking)
                _notify_middleware_after(session_id, user_text, response.get("content", ""), config)

                return {
                    "response_text": _strip_emotion_tags(response.get("content", "") or "Calling tools..."),
                    "response_chunks": [response.get("content", "") or ""],
                    "messages": [ai_message],
                    "tool_calls": formatted_tool_calls,
                }
            else:
                full_response = response.get("content", "")
                logger.info(f"[{session_id}] [LLMNode] LLM response: {full_response[:100]}...")
                ai_message = AIMessage(content=full_response)

                # after_llm_call notification (non-blocking)
                _notify_middleware_after(session_id, user_text, full_response, config)

                return {
                    "response_text": _strip_emotion_tags(full_response),
                    "response_chunks": [full_response],
                    "messages": [ai_message],
                    "tool_calls": None,
                }

    except Exception as e:
        logger.error(f"[{session_id}] [LLMNode] Tool call failed: {e}")
        return await _llm_without_tools(session_id, state, service_context, config, memory_context)


async def _llm_without_tools(
    session_id: str,
    state: AgentState,
    service_context: Any,
    config: RunnableConfig | None = None,
    memory_context: str = "",
) -> dict[str, Any]:
    """Use streaming mode (no tools)"""
    user_text = state.get("user_text", "")
    llm_engine = service_context.llm_engine
    messages = list(state.get("messages", []))

    logger.info(f"[{session_id}] [LLMNode] Using streaming mode (no tools)")

    system_prompt = state.get("system_prompt", "")

    # Inject memory into system_prompt
    enriched_prompt = _enrich_system_prompt(system_prompt, memory_context)

    if (not messages or not isinstance(messages[0], SystemMessage)) and enriched_prompt:
        messages.insert(0, SystemMessage(content=enriched_prompt))

    user_id = state.get("user_id")
    user_name = state.get("user_name")

    if not messages or not isinstance(messages[-1], HumanMessage):
        content = f"[{user_name}]: {user_text}" if user_name else user_text
        messages.append(HumanMessage(content=content, name=user_id or "user"))

    interrupt_handler = get_interrupt_handler()
    interrupt_handler.clear_interrupt(session_id)

    chunks = []
    full_response = ""

    timeout_seconds = _get_config_value(config, "llm_timeout", TIMEOUT_SECONDS)

    t_llm = time_module.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            async for chunk in llm_engine.chat_stream(user_text, system_prompt=enriched_prompt):
                if interrupt_handler.is_interrupted(session_id):
                    logger.warning(f"[{session_id}] [LLMNode] Interrupt detected, stopping generation")
                    break
                chunks.append(chunk)
                full_response += chunk
                if len(chunks) % 10 == 0:
                    logger.debug(f"[{session_id}] [LLMNode] Received {len(chunks)} chunks...")
    except TimeoutError:
        llm_duration = (time_module.perf_counter() - t_llm) * 1000
        logger.warning(f"[{session_id}] [LLMNode] LLM timeout after {timeout_seconds}s, using fallback")
        await log_node_error(session_id, "llm_node", "timeout", duration_ms=llm_duration)
        full_response = FALLBACK_RESPONSE
        chunks = [FALLBACK_RESPONSE]

        ai_message = AIMessage(content=full_response)
        return {
            "response_text": _strip_emotion_tags(full_response),
            "response_chunks": chunks,
            "messages": [ai_message],
            "tool_calls": None,
            "metadata": {**state.get("metadata", {}), "error_type": "timeout"},
        }

    llm_duration = (time_module.perf_counter() - t_llm) * 1000

    logger.info(f"[{session_id}] [LLMNode] LLM response: {full_response[:100]}...")
    log_timing(state, "llm.api_call", llm_duration,
               f"chat_stream | chunks={len(chunks)} | ttfb_first_chunk=<see llm_engine.log>")

    ai_message = AIMessage(content=full_response)

    # after_llm_call notification (non-blocking)
    _notify_middleware_after(session_id, user_text, full_response, config)

    return {
        "response_text": _strip_emotion_tags(full_response),
        "response_chunks": chunks,
        "messages": [ai_message],
        "tool_calls": None,
        "metadata": {**state.get("metadata", {})},
    }
