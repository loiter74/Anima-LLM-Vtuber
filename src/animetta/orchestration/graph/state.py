"""LangGraph state definition"""

from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """LangGraph Agent state"""

    # Input
    input_type: str
    raw_audio: bytes | None
    user_text: str

    # LLM conversation
    messages: Annotated[Sequence[BaseMessage], add_messages]
    system_prompt: str | None

    # Tool calling
    tool_calls: list[dict[str, Any]] | None
    tool_results: list[dict[str, Any]] | None

    # Output
    response_text: str
    response_chunks: list[str]
    tts_audio: bytes | str | None
    emotion: str | None
    emotion_vad: tuple[float, float, float] | None  # VAD vector from emotion_node

    # Control
    control_signal: str | None

    # Metadata
    session_id: str
    persona: dict[str, Any] | None
    channel_id: str | None
    user_id: str | None
    user_name: str | None
    metadata: dict[str, Any]

    # Error handling
    error: str | None
    should_retry: bool
    retry_count: int

    # Performance timing (collected at runtime for analysis)
    _timings: list[dict[str, Any]]

    # Memory Evolution
    fuzzy_memories: list[dict[str, Any]]
    injection_tier: int
    user_query_depth: int
    meme_candidates: list[dict[str, Any]]
    meme_injected: bool

    # Personality
    personality_mode: str              # 'default' | 'streaming' | 'mood_xxx'
    personality_mood: str | None    # current mood override


def create_initial_state(
    session_id: str,
    input_type: str = "text",
    user_text: str = "",
    raw_audio: bytes | None = None,
    persona: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    channel_id: str | None = None,
    user_id: str | None = None,
    user_name: str | None = None,
) -> AgentState:
    """Create initial state"""
    return {
        "input_type": input_type,
        "raw_audio": raw_audio,
        "user_text": user_text,
        "messages": [],
        "system_prompt": system_prompt,
        "tool_calls": None,
        "tool_results": None,
        "response_text": "",
        "response_chunks": [],
        "tts_audio": None,
        "emotion": None,
        "emotion_vad": None,
        "control_signal": None,
        "session_id": session_id,
        "persona": persona or {},
        "channel_id": channel_id,
        "user_id": user_id,
        "user_name": user_name,
        "metadata": {},
        "error": None,
        "should_retry": False,
        "retry_count": 0,
        "_timings": [],
        # Memory Evolution
        "fuzzy_memories": [],
        "injection_tier": 1,
        "user_query_depth": 0,
        "meme_candidates": [],
        "meme_injected": False,
        # Personality
        "personality_mode": "default",
        "personality_mood": None,
    }


def create_user_message(text: str, user_id: str | None = None, user_name: str | None = None) -> HumanMessage:
    """Create user message"""
    content = f"[{user_name}]: {text}" if user_name else text
    return HumanMessage(content=content, name=user_id or "user")


def create_ai_message(text: str) -> AIMessage:
    """Create AI message"""
    return AIMessage(content=text)


def create_system_message(text: str) -> SystemMessage:
    """Create system message"""
    return SystemMessage(content=text)


# ---------------------------------------------------------------------------
# Timing helper – appends timing entries to AgentState._timings
# ---------------------------------------------------------------------------

def log_timing(state: AgentState, step: str, duration_ms: float, detail: str = "") -> None:
    """Append a timing entry to the state for performance analysis."""
    timings = state.get("_timings", [])
    timings.append({
        "step": step,
        "duration_ms": round(duration_ms, 2),
        "detail": detail,
    })
    state["_timings"] = timings
