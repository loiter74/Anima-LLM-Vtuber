"""LangGraph state definition"""

from collections.abc import Sequence
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

# Affinity defaults — borrowed from the Galgame/VTuber "好感度" convention.
# Initial 50 = neutral first impression. Range [0, 100].
DEFAULT_AFFINITY: int = 50
AFFINITY_MIN: int = 0
AFFINITY_MAX: int = 100


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
    media_status: Any | None
    emotion: str | None
    emotion_vad: tuple[float, float, float] | None  # VAD vector from emotion_node
    # Explicit channels prevent a previous model response from biasing recall.
    conversation_emotion: str | None
    conversation_emotion_vad: tuple[float, float, float] | None
    response_emotion: str | None
    response_emotion_vad: tuple[float, float, float] | None

    # Control
    control_signal: str | None

    # Metadata
    session_id: str
    persona: dict[str, Any] | None
    channel_id: str | None
    user_id: str | None
    user_name: str | None
    message_id: str | None
    conversation_id: str | None
    task_id: str | None
    turn_id: str | None
    metadata: dict[str, Any]
    config_version: int

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
    personality_mode: str  # 'default' | 'streaming' | 'mood_xxx'
    personality_mood: str | None  # current mood override

    # Affinity — Galgame-style affection counter for the current 旅人.
    # Per-turn overlay: parsed from the LLM's `[affinity:N]` marker on the
    # previous turn (see llm_node._extract_and_update_affinity). Not persisted
    # across sessions; resets to DEFAULT_AFFINITY on a fresh conversation.
    affinity: int

    # Golden dialogue internals. Content is task-scoped and must be cleared by
    # the finalizer; it is never copied into metadata or persistence sinks.
    turn_scratch: dict[str, Any]


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
    message_id: str | None = None,
    conversation_id: str | None = None,
    task_id: str | None = None,
    turn_id: str | None = None,
) -> AgentState:
    """Create initial state"""
    message_id = message_id or str(uuid4())
    conversation_id = conversation_id or str(uuid4())
    task_id = task_id or turn_id or str(uuid4())
    turn_id = task_id
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
        "media_status": None,
        "emotion": None,
        "emotion_vad": None,
        "conversation_emotion": None,
        "conversation_emotion_vad": None,
        "response_emotion": None,
        "response_emotion_vad": None,
        "control_signal": None,
        "session_id": session_id,
        "persona": persona or {},
        "channel_id": channel_id,
        "user_id": user_id,
        "user_name": user_name,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "task_id": task_id,
        "turn_id": turn_id,
        "metadata": {},
        "config_version": 1,
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
        # Affinity — neutral first impression (DEFAULT_AFFINITY=50)
        "affinity": DEFAULT_AFFINITY,
        "turn_scratch": {},
    }


def create_user_message(
    text: str, user_id: str | None = None, user_name: str | None = None
) -> HumanMessage:
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
    timings.append(
        {
            "step": step,
            "duration_ms": round(duration_ms, 2),
            "detail": detail,
        }
    )
    state["_timings"] = timings
