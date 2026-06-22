from __future__ import annotations

from animetta.orchestration.graph.state import AgentState

"""Tests for LangGraph state definition and helpers."""


from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from animetta.orchestration.graph.state import (
    create_ai_message,
    create_initial_state,
    create_system_message,
    create_user_message,
    log_timing,
)

# ── AgentState TypedDict ────────────────────────────────────────────────


class TestAgentStateKeys:
    """AgentState TypedDict has the correct structural keys."""

    def test_all_expected_keys_present(self):
        """Every field documented in AgentState should be present."""
        keys = set(AgentState.__annotations__.keys())
        expected = {
            # Input
            "input_type",
            "raw_audio",
            "user_text",
            # LLM conversation
            "messages",
            "system_prompt",
            # Tool calling
            "tool_calls",
            "tool_results",
            # Output
            "response_text",
            "response_chunks",
            "tts_audio",
            "emotion",
            "emotion_vad",
            # Control
            "control_signal",
            # Metadata
            "session_id",
            "persona",
            "channel_id",
            "user_id",
            "user_name",
            "metadata",
            # Error handling
            "error",
            "should_retry",
            "retry_count",
            # Performance timing
            "_timings",
            # Memory Evolution
            "fuzzy_memories",
            "injection_tier",
            "user_query_depth",
            "meme_candidates",
            "meme_injected",
            # Personality
            "personality_mode",
            "personality_mood",
        }
        assert keys == expected, f"Missing or extra keys: {keys ^ expected}"

    def test_messages_annotated_with_add_messages(self):
        """The messages field uses the add_messages reducer annotation."""
        annotation = AgentState.__annotations__["messages"]
        # Python 3.13 stores Annotated metadata in __metadata__
        assert add_messages in annotation.__metadata__


# ── create_initial_state ────────────────────────────────────────────────


class TestCreateInitialState:
    """create_initial_state() produces a valid default state."""

    def test_returns_dict_with_all_keys(self):
        """The returned dict contains every AgentState key."""
        state = create_initial_state(session_id="sess_01")
        keys = set(AgentState.__annotations__.keys())
        assert set(state.keys()) == keys

    def test_session_id_is_set(self):
        """session_id is propagated correctly."""
        state = create_initial_state(session_id="custom_id")
        assert state["session_id"] == "custom_id"

    def test_default_values(self):
        """Default values match expectations."""
        state = create_initial_state(session_id="sess_01")
        assert state["input_type"] == "text"
        assert state["user_text"] == ""
        assert state["raw_audio"] is None
        assert state["messages"] == []
        assert state["system_prompt"] is None
        assert state["tool_calls"] is None
        assert state["tool_results"] is None
        assert state["response_text"] == ""
        assert state["response_chunks"] == []
        assert state["tts_audio"] is None
        assert state["emotion"] is None
        assert state["control_signal"] is None
        assert state["persona"] == {}
        assert state["channel_id"] is None
        assert state["user_id"] is None
        assert state["user_name"] is None
        assert state["metadata"] == {}
        assert state["error"] is None
        assert state["should_retry"] is False
        assert state["retry_count"] == 0
        assert state["_timings"] == []
        # Memory Evolution defaults
        assert state["fuzzy_memories"] == []
        assert state["injection_tier"] == 1
        assert state["user_query_depth"] == 0
        assert state["meme_candidates"] == []
        assert state["meme_injected"] is False
        # Personality defaults
        assert state["personality_mode"] == "default"
        assert state["personality_mood"] is None

    def test_override_input_type(self):
        """input_type can be overridden."""
        state = create_initial_state(session_id="sess_01", input_type="audio")
        assert state["input_type"] == "audio"

    def test_override_raw_audio(self):
        """raw_audio can be provided."""
        state = create_initial_state(session_id="sess_01", raw_audio=b"\x00\x01")
        assert state["raw_audio"] == b"\x00\x01"

    def test_override_user_text(self):
        """user_text can be provided."""
        state = create_initial_state(session_id="sess_01", user_text="Hello")
        assert state["user_text"] == "Hello"

    def test_override_persona(self):
        """persona dict is stored as-is."""
        persona = {"name": "Anima"}
        state = create_initial_state(session_id="sess_01", persona=persona)
        assert state["persona"] == persona

    def test_persona_defaults_to_empty_dict(self):
        """When persona is None, defaults to {}."""
        state = create_initial_state(session_id="sess_01", persona=None)
        assert state["persona"] == {}

    def test_override_system_prompt(self):
        """system_prompt can be provided."""
        state = create_initial_state(
            session_id="sess_01", system_prompt="Be helpful."
        )
        assert state["system_prompt"] == "Be helpful."

    def test_metadata_mutable_per_call(self):
        """Each call returns a fresh dict (no shared mutation)."""
        s1 = create_initial_state(session_id="a")
        s2 = create_initial_state(session_id="b")
        s1["metadata"]["key"] = "val"
        assert s2["metadata"] == {}

    def test_persona_mutable_per_call(self):
        """Each call returns a fresh persona dict."""
        s1 = create_initial_state(session_id="a")
        s2 = create_initial_state(session_id="b")
        s1["persona"]["name"] = "test"
        assert s2["persona"] == {}

    def test_channel_user_ids(self):
        """Channel and user identifiers are passed through."""
        state = create_initial_state(
            session_id="sess_01",
            channel_id="ch_1",
            user_id="uid_42",
            user_name="Alice",
        )
        assert state["channel_id"] == "ch_1"
        assert state["user_id"] == "uid_42"
        assert state["user_name"] == "Alice"


# ── Message helpers ─────────────────────────────────────────────────────


class TestCreateUserMessage:
    """create_user_message() builds a HumanMessage."""

    def test_basic_message(self):
        """Minimal call produces a HumanMessage with the given text."""
        msg = create_user_message("hello")
        assert isinstance(msg, HumanMessage)
        assert msg.content == "hello"
        assert msg.name == "user"

    def test_without_user_name(self):
        """When user_name is None, content is just the text."""
        msg = create_user_message("hello", user_id="uid_1")
        assert msg.content == "hello"
        assert msg.name == "uid_1"

    def test_with_user_name(self):
        """When user_name is provided, content is prepended."""
        msg = create_user_message("hello", user_name="Alice")
        assert msg.content == "[Alice]: hello"
        assert msg.name == "user"

    def test_with_user_name_and_id(self):
        """Both user_name and user_id are reflected."""
        msg = create_user_message("hi", user_id="uid_99", user_name="Bob")
        assert msg.content == "[Bob]: hi"
        assert msg.name == "uid_99"

    def test_empty_text(self):
        """Empty text still produces a valid HumanMessage."""
        msg = create_user_message("")
        assert msg.content == ""
        assert msg.name == "user"


class TestCreateAIMessage:
    """create_ai_message() builds an AIMessage."""

    def test_basic_ai_message(self):
        """Produces an AIMessage with the given text."""
        msg = create_ai_message("Hello, I am Anima.")
        assert isinstance(msg, AIMessage)
        assert msg.content == "Hello, I am Anima."

    def test_empty_text(self):
        """Empty text produces a valid AIMessage."""
        msg = create_ai_message("")
        assert msg.content == ""
        assert isinstance(msg, AIMessage)


class TestCreateSystemMessage:
    """create_system_message() builds a SystemMessage."""

    def test_basic_system_message(self):
        """Produces a SystemMessage with the given text."""
        msg = create_system_message("You are a helpful assistant.")
        assert isinstance(msg, SystemMessage)
        assert msg.content == "You are a helpful assistant."

    def test_empty_text(self):
        """Empty text produces a valid SystemMessage."""
        msg = create_system_message("")
        assert msg.content == ""
        assert isinstance(msg, SystemMessage)

    def test_multiline_content(self):
        """Multiline content is preserved."""
        text = "Line 1\nLine 2\nLine 3"
        msg = create_system_message(text)
        assert msg.content == text


# ── log_timing ──────────────────────────────────────────────────────────


class TestLogTiming:
    """log_timing() appends timing entries to state."""

    def test_appends_timing_entry(self):
        """A single timing entry is appended to _timings."""
        state = create_initial_state(session_id="sess_01")
        log_timing(state, "llm_call", 150.5)
        assert len(state["_timings"]) == 1
        entry = state["_timings"][0]
        assert entry["step"] == "llm_call"
        assert entry["duration_ms"] == 150.5
        assert entry["detail"] == ""

    def test_appends_multiple_entries(self):
        """Multiple calls accumulate entries in order."""
        state = create_initial_state(session_id="sess_01")
        log_timing(state, "step_a", 10.0)
        log_timing(state, "step_b", 20.0)
        assert len(state["_timings"]) == 2
        assert state["_timings"][0]["step"] == "step_a"
        assert state["_timings"][1]["step"] == "step_b"

    def test_with_detail(self):
        """An optional detail string is stored."""
        state = create_initial_state(session_id="sess_01")
        log_timing(state, "tts", 300.0, detail="voice_id=xyz")
        entry = state["_timings"][0]
        assert entry["detail"] == "voice_id=xyz"

    def test_duration_rounded_to_two_decimals(self):
        """duration_ms is rounded to 2 decimal places."""
        state = create_initial_state(session_id="sess_01")
        log_timing(state, "test", 123.4567)
        assert state["_timings"][0]["duration_ms"] == 123.46

    def test_works_with_state_missing_timings_key(self):
        """log_timing gracefully handles a state dict without _timings."""
        state = create_initial_state(session_id="sess_01")
        del state["_timings"]
        log_timing(state, "orphan", 99.0)
        assert len(state["_timings"]) == 1
        assert state["_timings"][0]["step"] == "orphan"
        assert state["_timings"][0]["duration_ms"] == 99.0

    def test_mutates_state_in_place(self):
        """The state dict is mutated in-place (same object reference)."""
        state = create_initial_state(session_id="sess_01")
        original_id = id(state["_timings"])
        log_timing(state, "x", 1.0)
        assert id(state["_timings"]) == original_id
