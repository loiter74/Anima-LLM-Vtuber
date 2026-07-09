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
from .state import AFFINITY_MAX, AFFINITY_MIN, AgentState, log_timing

# Configurable timeout for LLM provider calls (default: 30 seconds)
TIMEOUT_SECONDS = 30
FALLBACK_RESPONSE = "I need a moment to think about that."

# Regex for emotion tags like [happy], [neutral], [sad]. Does NOT match
# ``[affinity:N]`` — affinity marker stripping is handled exclusively by
# ``_extract_and_update_affinity`` (which respects the 【debug】 visibility
# switch). Keeping these regexes separate prevents the emotion stripper from
# clobbering a marker that the affinity parser deliberately preserved.
_EMOTION_TAG_RE = re.compile(r"\s*\[[\w-]+\]\s*")
_THINKING_BLOCK_RE = re.compile(
    r"(?is)<(?:think|thinking)\b[^>]*>.*?</(?:think|thinking)>"
    r"|\[(?:think|thinking)\].*?\[/(?:think|thinking)\]"
)
_ORPHAN_THINKING_PREFIX_RE = re.compile(
    r"(?is)^.*?(?:</(?:think|thinking)>|\[/(?:think|thinking)\])\s*"
)
_UNTAGGED_REASONING_PREFIX_RE = re.compile(
    r"(?is)^\s*"
    r"(?=(?:the user\s+(?:says|said|asks|asked|wants|is)\b|"
    r"user\s+(?:says|said|asks|asked|wants|is)\b|"
    r"as an?\b|i should\b|let me\b))"
    r"(?=.*\b(?:i should|let me|actually|respond in character|"
    r"not a minecraft command|usual style)\b)"
    r".*[.!?]\s+"
    r"(?P<answer>[\u4e00-\u9fff][\s\S]*)$"
)
_CHINESE_UNTAGGED_REASONING_PREFIX_RE = re.compile(
    r"(?s)^\s*"
    r"(?=(?:用户(?:问|说|想|要|发|在)|作为AI|作为Anima|我(?:需要|应该|知道|可以|得)|这个问题|实际上))"
    r"(?=.*(?:作为AI|作为Anima|符合人设|对话历史|方式来回应|假装记得|保持神秘感|这是个测试|实际上))"
    r".*?[。！？]\s*"
    r"(?P<answer>(?:上一个话题|我的数据库告诉你|你(?:刚才|上次|刚刚)|哎呀|这就|赛博酒馆|后厨|牛到了|欢迎光临|来都来了)[\s\S]*)$"
)
_CHINESE_REASONING_START_RE = re.compile(
    r"^\s*(?:用户(?:问|说|想|要|发|在|继续|再次|测试|表示|让)|作为(?:AI|Anima)|我(?:需要|应该|知道|可以|得))"
)
_CHINESE_SENTENCE_RE = re.compile(r"[^。！？]*[。！？]\s*")
_CHINESE_REASONING_SIGNAL_RE = re.compile(
    r"(?:用户(?:问|说|想|要|发|在|继续|再次|测试|表示|让)|作为AI|作为Anima|AI VTuber|"
    r"我(?:需要|应该|知道|可以|得)|符合人设|对话历史|方式来回应|方式回应|"
    r"假装记得|保持神秘感|这是(?:个)?测试|实际上|弹幕|轻吐槽|自然收住|"
    r"调用工具|不要解释|不要写分析|不要跳出角色|角色内|保持[^。！？]{0,30}语气)"
    r"|连续对话检查|承认上下文|保持角色感|这个问题有点意思"
)

# Affinity marker — ``[affinity:N]`` where N is a signed int (clamped later).
# The LLM emits this at the end of each reply per the AffinityPromptSource
# contract. Parsed value flows into state["affinity"] + metadata for the next
# turn's prompt overlay.
_AFFINITY_MARKER_RE = re.compile(r"\[affinity:(-?\d+)\]")
_SENTENCE_END_RE = re.compile(r"([^。！？!?]+)([。！？!?])")


def _strip_emotion_tags(text: str) -> str:
    """Remove emotion tags like [happy], [neutral] from LLM output."""
    return _EMOTION_TAG_RE.sub(" ", text).strip()


def _strip_model_thinking(text: str) -> str:
    """Remove provider-emitted thinking blocks before exposing visible replies."""
    if not text:
        return text

    stripped = _THINKING_BLOCK_RE.sub("", text)
    stripped = _ORPHAN_THINKING_PREFIX_RE.sub("", stripped, count=1)
    match = _UNTAGGED_REASONING_PREFIX_RE.match(stripped)
    if match:
        stripped = match.group("answer")
    else:
        stripped = _strip_chinese_untagged_reasoning_prefix(stripped)
    return stripped.strip()


def _strip_chinese_untagged_reasoning_prefix(text: str) -> str:
    """Strip Chinese meta-reasoning sentences before the visible character reply."""
    if not _CHINESE_REASONING_START_RE.match(text):
        return text

    pos = 0
    reasoning_sentence_count = 0
    while match := _CHINESE_SENTENCE_RE.match(text, pos):
        sentence = match.group(0)
        if not _CHINESE_REASONING_SIGNAL_RE.search(sentence):
            break
        reasoning_sentence_count += 1
        pos = match.end()

    if reasoning_sentence_count >= 2 and pos < len(text):
        return text[pos:].lstrip()

    fallback_match = _CHINESE_UNTAGGED_REASONING_PREFIX_RE.match(text)
    if fallback_match:
        return fallback_match.group("answer")
    return text


def _enforce_persona_verbal_tics(response_text: str, system_prompt: str | None) -> str:
    """Apply explicit persona verbal-tic hard rules to visible replies.

    This is intentionally narrow: it only handles the Anima v0.1-style
    "每一句话后面都要加上喵" rule when it appears in the compiled prompt.
    """
    if not response_text or not system_prompt:
        return response_text
    if "每一句话后面都要加上喵" not in system_prompt:
        return response_text

    def _add_nya(match: re.Match[str]) -> str:
        body = match.group(1).rstrip()
        punct = match.group(2)
        if body.endswith("喵"):
            return f"{body}{punct}"
        return f"{body}喵{punct}"

    rewritten = _SENTENCE_END_RE.sub(_add_nya, response_text)
    if rewritten == response_text and response_text.strip() and not response_text.rstrip().endswith("喵"):
        return f"{response_text.rstrip()}喵"
    return rewritten


def _extract_and_update_affinity(state: dict[str, Any], response_text: str) -> str:
    """Parse the LLM's ``[affinity:N]`` marker, write the value back to state.

    The marker is Galgame-style self-report: the LLM emits its updated
    affection toward the 旅人 at the end of each reply (per
    AffinityPromptSource contract). We:
    1. Find the last ``[affinity:N]`` occurrence (in case of repetition).
    2. Clamp to ``[AFFINITY_MIN, AFFINITY_MAX]``.
    3. Write to ``state["affinity"]`` and ``state["metadata"]["affinity"]``
       so the next turn's build_context() picks it up.
    4. Return the response text with the marker stripped — UNLESS the user
       sent ``【debug】`` on this turn, in which case the marker is kept
       visible (per the affinity_marker special_behavior contract).

    If no marker is present, ``state["affinity"]`` is left untouched (the
    previous turn's value carries over via metadata) and the text is
    returned unchanged.

    Args:
        state: AgentState dict (mutated in place — affinity + metadata).
        response_text: Raw LLM response (may contain ``[affinity:N]``).

    Returns:
        The response text; marker stripped unless this is a 【debug】 turn.
    """
    matches = _AFFINITY_MARKER_RE.findall(response_text or "")
    if not matches:
        return response_text

    # Last match wins (LLM sometimes double-emits; final value is canonical).
    raw_value = int(matches[-1])
    clamped = max(AFFINITY_MIN, min(AFFINITY_MAX, raw_value))
    if clamped != raw_value:
        logger.debug(
            f"[affinity] LLM emitted out-of-range value {raw_value}; clamped to {clamped}"
        )

    state["affinity"] = clamped
    metadata = state.setdefault("metadata", {})
    metadata["affinity"] = clamped
    logger.info(f"[affinity] Updated to {clamped}/100")

    # 【debug】 visibility switch: if the user asked for debug this turn,
    # keep the marker so they can see the raw value. Otherwise strip it.
    user_text = state.get("user_text", "") or ""
    if "【debug】" in user_text:
        logger.debug("[affinity] 【debug】 turn — keeping marker visible")
        return response_text

    # Strip ALL affinity markers from the visible text.
    return _AFFINITY_MARKER_RE.sub("", response_text)

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
    character_known: list[str] | None = None,
    character_unknown: list[str] | None = None,
    mbti_ei: int = 50,
    mbti_sn: int = 50,
    mbti_tf: int = 50,
    mbti_jp: int = 50,
) -> tuple[str, dict]:
    """
    Retrieve memory context via LivingMemorySystem V2 recall().

    Args:
        session_id: Session ID
        query: Query text (user input)
        config: LangGraph config
        max_turns: Maximum number of turns to retrieve
        current_emotion: VADVector for mood-congruent recall
        character_known: Character's known knowledge domains (from persona config)
        character_unknown: Character's unknown knowledge domains (excluded from recall)
        mbti_ei, mbti_sn, mbti_tf, mbti_jp: MBTI dimensions for persona-biased ranking

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
            character_known=character_known,
            character_unknown=character_unknown,
            mbti_ei=mbti_ei,
            mbti_sn=mbti_sn,
            mbti_tf=mbti_tf,
            mbti_jp=mbti_jp,
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
    Inject memory context into the system prompt.

    .. deprecated::
        Use ``orchestration.prompting.pipeline.compile()`` instead.
        Kept only for backward compatibility with existing tests and callers.
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
    _meta = state.get("metadata", {})
    retrieval_result = await _retrieve_memory_context(
        session_id=session_id,
        query=user_text,
        config=config,
        max_turns=5,
        current_emotion=current_emotion,
        character_known=_meta.get("character_known"),
        character_unknown=_meta.get("character_unknown"),
        mbti_ei=_meta.get("mbti_ei", 50),
        mbti_sn=_meta.get("mbti_sn", 50),
        mbti_tf=_meta.get("mbti_tf", 50),
        mbti_jp=_meta.get("mbti_jp", 50),
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

    # Compile final system prompt via pipeline (replaces manual concatenation)
    from animetta.orchestration.prompting.pipeline import compile as compile_prompt
    compiled = await compile_prompt(state, config, memory_context=memory_context)
    enriched_prompt = compiled.system_prompt

    if compiled.warnings:
        logger.debug(f"[{session_id}] [LLMNode] Prompt warnings: {compiled.warnings}")
    logger.info(
        f"[{session_id}] [LLMNode] Compiled prompt: {compiled.section_count} sections, "
        f"memory={compiled.memory_included}"
    )

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

                visible_content = _strip_model_thinking(response.get("content", "") or "Calling tools...")
                visible_content = _strip_emotion_tags(visible_content)
                ai_message = AIMessage(content=visible_content, tool_calls=tool_calls)

                # after_llm_call notification (non-blocking)
                _notify_middleware_after(session_id, user_text, visible_content, config)

                return {
                    "response_text": visible_content,
                    "response_chunks": [visible_content],
                    "messages": [ai_message],
                    "tool_calls": formatted_tool_calls,
                }
            else:
                full_response = _strip_model_thinking(response.get("content", ""))
                logger.info(f"[{session_id}] [LLMNode] LLM response: {full_response[:100]}...")

                # ── Affinity marker parsing ── (same as streaming path)
                full_response = _extract_and_update_affinity(state, full_response)
                original_response = full_response
                full_response = _enforce_persona_verbal_tics(full_response, enriched_prompt)
                response_chunks = [full_response if full_response != original_response else original_response]
                # after_llm_call notification (non-blocking)
                _notify_middleware_after(session_id, user_text, full_response, config)

                return {
                    "response_text": _strip_emotion_tags(full_response),
                    "response_chunks": response_chunks,
                    "tool_calls": None,
                    "metadata": {**state.get("metadata", {})},
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

    # Compile final system prompt via pipeline (replaces manual concatenation)
    from animetta.orchestration.prompting.pipeline import compile as compile_prompt
    compiled = await compile_prompt(state, config, memory_context=memory_context)
    enriched_prompt = compiled.system_prompt

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

        # Note: no affinity marker in the FALLBACK_RESPONSE, so the value
        # carries over from the previous turn (correct behavior — we did not
        # actually talk to the 旅人, affection shouldn't shift).
        return {
            "response_text": _strip_emotion_tags(full_response),
            "response_chunks": chunks,
            "tool_calls": None,
            "metadata": {**state.get("metadata", {}), "error_type": "timeout"},
        }

    llm_duration = (time_module.perf_counter() - t_llm) * 1000

    logger.info(f"[{session_id}] [LLMNode] LLM response: {full_response[:100]}...")
    log_timing(state, "llm.api_call", llm_duration,
               f"chat_stream | chunks={len(chunks)} | ttfb_first_chunk=<see llm_engine.log>")

    # ── Affinity marker parsing ──
    # Extract [affinity:N] (mutates state + metadata) and strip the marker
    # from the visible text. Done before AIMessage construction so the chat
    # history (used for roleplay-guard drift detection next turn) doesn't
    # carry stale markers.
    raw_response = full_response
    full_response = _strip_model_thinking(full_response)
    full_response = _extract_and_update_affinity(state, full_response)
    original_response = full_response
    full_response = _enforce_persona_verbal_tics(full_response, enriched_prompt)
    # Also strip any chunks that may contain the marker (defensive — the
    # streaming chunks accumulate the raw marker).
    chunks = [full_response] if full_response != raw_response or full_response != original_response else [
        _AFFINITY_MARKER_RE.sub("", c) for c in chunks
    ]

    # after_llm_call notification (non-blocking)
    _notify_middleware_after(session_id, user_text, full_response, config)

    return {
        "response_text": _strip_emotion_tags(full_response),
        "response_chunks": chunks,
        "tool_calls": None,
        "metadata": {**state.get("metadata", {})},
    }
