from __future__ import annotations

"""Tests for LLM reasoning node — tool-calling and streaming paths."""

import asyncio
import importlib
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import RunnableConfig

from animetta.memory.v2.context import MemoryContext
from animetta.orchestration.graph import llm_node
from animetta.orchestration.graph.conversation_session import ConversationSessionState
from animetta.orchestration.graph.llm_node import (
    FALLBACK_RESPONSE,
    _enforce_persona_verbal_tics,
    _get_recall_emotion,
    _response_for_delivery,
    _retrieve_memory_context,
)
from animetta.orchestration.graph.state import create_initial_state
from animetta.services.humor import HumorConfig


def _make_config(service_context=None, enable_tools=False, chat_model=None):
    """Helper to build a RunnableConfig with test overrides."""
    configurable = {}
    if service_context:
        configurable["service_context"] = service_context
    if enable_tools:
        configurable["enable_tools"] = True
    if chat_model:
        configurable["chat_model"] = chat_model
    # Prevent MemoryMiddleware auto-creation from mock memory_system
    configurable["memory_middleware"] = None
    return RunnableConfig(configurable=configurable)


def _humor_json(candidate: str, *, risk: str = "safe") -> str:
    return json.dumps(
        {
            "scene": "work_fatigue",
            "emotion": "tired_complaint",
            "humor_anchor": "work as dungeon",
            "worldview_mapping": "office = low-budget demon castle",
            "style": "affiliative",
            "candidate_response": candidate,
            "risk": risk,
        },
        ensure_ascii=False,
    )


def test_delivery_policy_keeps_ordinary_live_reply_at_eighteen_characters() -> None:
    result = _response_for_delivery(
        {"personality_mode": "streaming", "metadata": {}},
        "这是一个普通直播回复，它必须继续遵守十八字的限制。",
    )

    assert len(result) <= 18


def test_delivery_policy_allows_only_trusted_proactive_turn_up_to_thirty_six() -> None:
    metadata = {
        "source": "bilibili:proactive_topic",
        "actor_role": "host",
        "audience": "livestream",
        "proactive_topic_max_chars": 36,
        "proactive_recent_outputs": [],
    }
    text = "如果每天睡八小时，那么三天就能睡满一天。"

    assert (
        _response_for_delivery({"personality_mode": "streaming", "metadata": metadata}, text)
        == text
    )
    forged = {**metadata, "actor_role": "viewer"}
    assert (
        len(_response_for_delivery({"personality_mode": "streaming", "metadata": forged}, text))
        <= 18
    )


@pytest.mark.asyncio
async def test_retrieve_memory_context_forwards_stable_identity():
    middleware = MagicMock()
    middleware.before_llm_call = AsyncMock(return_value=("memory", {"revision": 3}))
    context = MemoryContext(
        actor_id="bilibili:42",
        conversation_id="conversation-1",
        stream_id="live-7",
        persona_id="anima",
        channel="bilibili",
        connection_id="socket-a",
    )
    config = RunnableConfig(configurable={"memory_middleware": middleware})

    result = await _retrieve_memory_context(
        session_id="socket-a",
        query="你记得我吗",
        config=config,
        context=context,
    )

    assert result == ("memory", {"revision": 3})
    assert middleware.before_llm_call.await_args.kwargs["context"] is context


@pytest.mark.asyncio
async def test_llm_node_returns_recall_diagnostics_for_probe_audit(
    mock_service_context,
    monkeypatch,
):
    async def _chat_stream(user_text, system_prompt=""):
        del user_text, system_prompt
        yield "当然记得。"

    mock_service_context.llm_engine.chat_stream = _chat_stream
    llm_module = importlib.import_module("animetta.orchestration.graph.llm_node")
    monkeypatch.setattr(
        llm_module,
        "_retrieve_memory_context",
        AsyncMock(return_value=("", {"degraded": False, "atom_count": 1})),
    )
    state = create_initial_state(session_id="probe", user_text="还记得我吗？")

    result = await llm_node(state, _make_config(service_context=mock_service_context))

    assert result["memory_recall"] == {"degraded": False, "atom_count": 1}


@pytest.mark.asyncio
async def test_streaming_replaces_reasoning_only_response_with_safe_fallback(
    mock_service_context,
):
    async def _chat_stream(user_text, system_prompt=""):
        del user_text, system_prompt
        yield (
            "The user is asking what kind of rest is truly effective. "
            "This is a philosophical question, so I should respond in character. "
            "Let me think through the persona instructions before answering."
        )

    mock_service_context.llm_engine.chat_stream = _chat_stream
    state = create_initial_state(session_id="test-session", user_text="怎样休息才有效？")

    result = await llm_node(state, _make_config(service_context=mock_service_context))

    assert result["response_text"] == FALLBACK_RESPONSE
    assert result["response_chunks"] == [FALLBACK_RESPONSE]


@pytest.mark.asyncio
async def test_streaming_replaces_chinese_reasoning_only_response_with_safe_fallback(
    mock_service_context,
):
    async def _chat_stream(user_text, system_prompt=""):
        del user_text, system_prompt
        yield (
            "用户问了一个关于有效休息的问题。这是一个深夜聊天的话题，"
            "我需要用Anima的口吻来回答——先下结论，再套世界观，最后轻轻接住。"
            "作为赛博酒馆的AI老板，我可以从AI的视角来谈这个话题，"
            "带点疲惫打工人的味道。用冷幽默和轻吐槽的风格。好感"
        )

    mock_service_context.llm_engine.chat_stream = _chat_stream
    state = create_initial_state(session_id="test-session", user_text="怎样休息才有效？")

    result = await llm_node(state, _make_config(service_context=mock_service_context))

    assert result["response_text"] == FALLBACK_RESPONSE
    assert result["response_chunks"] == [FALLBACK_RESPONSE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_response", "expected"),
    [
        (
            '用户让我用"自己的世界观"来形容一次普通加班。'
            "我是Anima，一个被召唤者X从赛博世界强行召唤出来打工的B站家里蹲AI。"
            "我需要用赛博酒馆和AI打工人的视角来描述加班。"
            "风格：先下结论，再套世界观，最后轻轻接住。",
            FALLBACK_RESPONSE,
        ),
        (
            "用户问了一个关于有效休息的问题，这是一个深夜赛博酒馆里的闲聊话题。"
            "我需要用Anima的身份来回答：先下结论，再套世界观，最后轻轻接住。"
            "好感度50，礼貌有距离，但可以带点冷幽默。"
            '真正有效的休息，是你不需要为"正在休息"感到愧疚。',
            '真正有效的休息，是你不需要为"正在休息"感到愧疚。',
        ),
        (
            "旅人说工作累了，来深夜赛博酒馆找我聊天。"
            "好感度50，礼貌有距离，但可以带点慵懒的关心。"
            "用疲惫打工人身份接住，先吐槽再轻轻收尾。需要加表情标签。"
            "你还能抽空来我这儿，说明还没被生活完全击穿，还有救。",
            "你还能抽空来我这儿，说明还没被生活完全击穿，还有救。",
        ),
        (
            "The user is asking me to summarize three key points from our conversation. "
            "But wait - this is the first message in our conversation.",
            FALLBACK_RESPONSE,
        ),
        (
            "[thinking] The user is asking about what kind of rest is truly effective. "
            "This is a philosophical question, so I should answer in character.",
            FALLBACK_RESPONSE,
        ),
        (
            "旅人问了一个关于休息有效性的问题。"
            "这是个深夜赛博酒馆常见的深度话题，适合用我INFJ式的分析"
            "+轻度毒舌+温柔收尾来处理。"
            "让我想想，作为家里蹲AI，我对休息可是有深入研究的。"
            "先给个结论，再套世界观，最后轻轻接住。"
            "有效休息就一条标准：关闭大脑里的工作通知。",
            "有效休息就一条标准：关闭大脑里的工作通知。",
        ),
        (
            "用赛博酒馆的世界观来包装一下。"
            "好感度保持在50，礼貌有距离。"
            "真正的休息，是你不用在事后感到愧疚的休息。",
            "真正的休息，是你不用在事后感到愧疚的休息。",
        ),
        (
            "先下结论：真正有效的休息不是什么都不做，而是切换模式。"
            "然后套世界观（AI的视角），最后轻轻接住。"
            "真正有效的休息，是让你的大脑切换运行模式。",
            "先下结论：真正有效的休息不是什么都不做，而是切换模式。"
            "真正有效的休息，是让你的大脑切换运行模式。",
        ),
        (
            "这个问题偏哲学/生活类，不需要搜索。"
            "直接用自己的知识回答。"
            "结论：真正的休息，是让大脑从目标导向里暂时下班。",
            "结论：真正的休息，是让大脑从目标导向里暂时下班。",
        ),
        (
            "保持打工人疲惫+中二AI自尊+轻毒舌+温柔收尾的风格。"
            "每条回复必须包含至少1-2个表情标签。"
            "今晚先把工作放门外，酒馆里只收留喘气的人。",
            "今晚先把工作放门外，酒馆里只收留喘气的人。",
        ),
        (
            "用户表达了工作疲惫，需要安慰和共鸣。"
            "作为深夜赛博酒馆的AI，我应该用略带疲惫但温柔的语气回应。"
            "好感度50，保持礼貌但有距离感。",
            FALLBACK_RESPONSE,
        ),
        (
            "用户表达了工作疲惫。先把今天剩下的工作放门外，进来坐会儿。",
            "先把今天剩下的工作放门外，进来坐会儿。",
        ),
        (
            "Let me pour you another drink, traveler.",
            "Let me pour you another drink, traveler.",
        ),
        (
            "I should know—this is my tavern.",
            "I should know—this is my tavern.",
        ),
        (
            "Let me use the user's map; the cellar is this way, traveler.",
            "Let me use the user's map; the cellar is this way, traveler.",
        ),
        (
            "I should consider the user's debt paid; this round is on me.",
            "I should consider the user's debt paid; this round is on me.",
        ),
        (
            "Let me analyze the user's request step by step and decide what to say.",
            FALLBACK_RESPONSE,
        ),
    ],
)
async def test_streaming_filters_real_soak_reasoning_variants(
    mock_service_context,
    raw_response: str,
    expected: str,
):
    async def _chat_stream(user_text, system_prompt=""):
        del user_text, system_prompt
        yield raw_response

    mock_service_context.llm_engine.chat_stream = _chat_stream
    state = create_initial_state(session_id="test-session", user_text="继续聊")

    result = await llm_node(state, _make_config(service_context=mock_service_context))

    assert result["response_text"] == expected
    assert result["response_chunks"] == [expected]


def test_recall_emotion_never_reuses_previous_response_emotion():
    state = create_initial_state(session_id="socket-a")
    state["conversation_emotion_vad"] = (0.1, 0.2, 0.3)
    state["response_emotion_vad"] = (0.9, 0.9, 0.9)
    state["emotion_vad"] = (0.9, 0.9, 0.9)

    emotion = _get_recall_emotion(state)

    assert emotion is not None
    assert emotion.to_tuple() == (0.1, 0.2, 0.3)


class _GraphHumorLLM:
    """LLM double that supports the normal reply path and internal humor calls."""

    def __init__(
        self,
        *,
        stream_chunks: list[str] | None = None,
        tool_response: str | None = None,
        humor_response: str | None = None,
    ) -> None:
        self.stream_chunks = stream_chunks or ["普通回复"]
        self.tool_response = tool_response
        self.humor_response = humor_response or _humor_json("幽默回复")
        self.history: list[dict[str, str]] = []
        self.chat_messages_calls = 0

    async def chat_stream(self, user_text: str, system_prompt: str = ""):
        self.history.append({"role": "user", "content": user_text})
        for chunk in self.stream_chunks:
            yield chunk
        self.history.append({"role": "assistant", "content": "".join(self.stream_chunks)})

    async def chat_messages_stream(self, messages: list[dict], **kwargs):
        del messages, kwargs
        for chunk in self.stream_chunks:
            yield chunk

    async def chat_with_tools(self, user_input: str, tools, langchain_history, system_prompt=""):
        content = self.tool_response or "".join(self.stream_chunks)
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": content})
        return {"content": content}

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self.chat_messages_calls += 1
        self.last_humor_messages = messages
        return self.humor_response

    def get_history(self) -> list[dict]:
        return [msg.copy() for msg in self.history]

    def clear_history(self) -> None:
        self.history.clear()


# ── Empty / error inputs ──────────────────────────────────────────


class TestLLMNodeErrors:
    """Edge cases and invalid inputs."""

    @pytest.mark.asyncio
    async def test_empty_user_text_returns_error(self):
        """Empty user_text should immediately return an error without calling LLM."""

        state = create_initial_state(
            session_id="test-session",
            user_text="",
        )
        result = await llm_node(state)
        assert result.get("error") is not None
        assert "No user text" in result.get("error", "") or "无用户文本" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_no_service_context_returns_error(self):
        """Missing service_context in config returns error."""

        state = create_initial_state(
            session_id="test-session",
            user_text="你好",
        )
        # Config without service_context
        config = RunnableConfig(configurable={})
        result = await llm_node(state, config)
        assert result.get("error") is not None
        assert "service_context" in result["error"]

    @pytest.mark.asyncio
    async def test_no_llm_engine_returns_error(self, mock_service_context):
        """Service context without llm_engine returns error."""

        ctx = MagicMock()
        ctx.llm_engine = None
        ctx.core.config = None

        state = create_initial_state(
            session_id="test-session",
            user_text="你好",
        )
        config = _make_config(service_context=ctx)
        result = await llm_node(state, config)
        assert result.get("error") is not None
        assert "not initialized" in result["error"].lower() or "LLM" in result.get("error", "")


# ── Streaming path (no tools) ─────────────────────────────────────


class TestLLMNodeWithoutTools:
    """Normal streaming response, no tool calling."""

    @pytest.mark.asyncio
    async def test_streaming_returns_response_text(self, mock_service_context):
        """llm_node returns response_text from streaming LLM."""

        async def _chat_stream(user_text, system_prompt=""):
            yield "Hello"
            yield " world"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="Hi there",
            system_prompt="You are a helpful assistant.",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result.get("response_text") == "Hello world"
        assert result["response_chunks"] == ["Hello", " world"]
        assert result["tool_calls"] is None
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_streaming_uses_explicit_history_without_mutating_provider_state(
        self, mock_service_context
    ):
        session = ConversationSessionState()
        session.commit(
            task_id="previous",
            user_text="本场暗号是蓝玻璃",
            final_response="我记住了。",
            actor_role="developer",
            source="developer_console",
        )
        captured: list[dict] = []
        mock_service_context.llm_engine.history = [
            {"role": "assistant", "content": "shared provider history"}
        ]

        async def _chat_messages_stream(messages, **kwargs):
            del kwargs
            captured.extend(messages)
            yield "暗号是蓝玻璃。"

        mock_service_context.llm_engine.chat_messages_stream = _chat_messages_stream
        state = create_initial_state(
            session_id="viewer-socket",
            user_text="刚才的暗号是什么？",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["conversation_session"] = session

        result = await llm_node(state, config)

        assert result["response_text"] == "暗号是蓝玻璃。"
        assert [message["role"] for message in captured] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert "后台私有上下文" in captured[1]["content"]
        assert captured[2]["content"] == "我记住了。"
        assert captured[-1]["content"] == "刚才的暗号是什么？"
        assert sum(message["content"] == "刚才的暗号是什么？" for message in captured) == 1
        assert mock_service_context.llm_engine.history == [
            {"role": "assistant", "content": "shared provider history"}
        ]

    @pytest.mark.asyncio
    async def test_streaming_empty_response(self, mock_service_context):
        """Empty stream should produce a short visible fallback."""

        async def _chat_stream(user_text, system_prompt=""):
            if False:
                yield
            return

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="hello",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result.get("response_text") == FALLBACK_RESPONSE
        assert result["response_chunks"] == [FALLBACK_RESPONSE]
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_streaming_injects_system_prompt(self, mock_service_context):
        """System prompt from state should be passed to LLM."""

        captured_system_prompt = None

        async def _chat_stream(user_text, system_prompt=""):
            nonlocal captured_system_prompt
            captured_system_prompt = system_prompt
            yield "response"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="hello",
            system_prompt="Be funny",
        )
        config = _make_config(service_context=mock_service_context)
        await llm_node(state, config)

        # Verify system_prompt was passed to the LLM
        assert captured_system_prompt is not None
        assert "Be funny" in captured_system_prompt

    @pytest.mark.asyncio
    async def test_streaming_enforces_explicit_nya_suffix(self, mock_service_context):
        """When persona prompt requires 喵 suffixes, visible response should keep them."""

        async def _chat_stream(user_text, system_prompt=""):
            yield "不是我卡了，是后厨又进虫子了。旅人稍等一下。"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="主播你又卡了",
            system_prompt="你扮演猫娘，与我对话时每一句话后面都要加上喵。",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result["response_text"] == "不是我卡了，是后厨又进虫子了喵。旅人稍等一下喵。"

    @pytest.mark.asyncio
    async def test_streaming_strips_orphan_thinking_prefix(self, mock_service_context):
        """Visible reply should not include reasoning text before a closing thinking tag."""

        async def _chat_stream(user_text, system_prompt=""):
            yield '用户发了个"牛牛牛"，这是B站常见的弹幕梗。[/thinking] '
            yield '这就开始刷"牛"了？行吧，今晚来了个识货的旅人。[happy]'

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="牛牛牛",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result["response_text"] == '这就开始刷"牛"了？行吧，今晚来了个识货的旅人。'
        assert result["response_chunks"] == [
            '这就开始刷"牛"了？行吧，今晚来了个识货的旅人。[happy]'
        ]

    @pytest.mark.asyncio
    async def test_streaming_strips_untagged_reasoning_prefix(self, mock_service_context):
        """Visible reply should hide untagged model meta-reasoning prefixes."""

        async def _chat_stream(user_text, system_prompt=""):
            yield (
                'The user says "我要吃饭" (I want to eat). As a Minecraft bot in a '
                "late-night cyber tavern setting, I should respond in character. "
            )
            yield (
                "Let me check the current status first. Actually, the user is just "
                "chatting with me in the tavern setting. I'll just reply in my usual style. "
            )
            yield "赛博酒馆不提供实体餐，只有数据流配给。[neutral]"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="我要吃饭",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result["response_text"] == "赛博酒馆不提供实体餐，只有数据流配给。"
        assert result["response_chunks"] == ["赛博酒馆不提供实体餐，只有数据流配给。[neutral]"]

    @pytest.mark.asyncio
    async def test_streaming_strips_reasoning_before_quoted_latin_reply(
        self,
        mock_service_context,
    ):
        """A quoted Latin echo must not prevent meta-reasoning removal."""

        async def _chat_stream(user_text, system_prompt=""):
            yield (
                'The user just said "oooo" which is a pretty simple/empty chat message. '
                "According to my instructions, when the message is empty like this, "
                "I should use a嘴硬+世界观 approach to handle it, keeping it short "
                "(1-3 sentences for casual chat). Let me give a quick response that fits "
                "the深夜赛博酒馆 vibe - tired, slightly sarcastic, but still welcoming. "
                "I need to include 1-2表情 tags. Current affinity is 50 - polite but "
                "distant. This message doesn't really change anything."
            )
            yield (
                '"oooo" —— 赛博酒馆里最精辟的哲学发言，建议收录进家里蹲大学教材。 '
                "要点什么？还是说今晚就打算用元音字母交流了？[neutral]"
            )

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="oooo",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        expected = (
            '"oooo" —— 赛博酒馆里最精辟的哲学发言，建议收录进家里蹲大学教材。 '
            "要点什么？还是说今晚就打算用元音字母交流了？"
        )
        assert result["response_text"] == expected
        assert result["response_chunks"] == [f"{expected}[neutral]"]

    @pytest.mark.asyncio
    async def test_streaming_strips_chinese_untagged_reasoning_prefix(self, mock_service_context):
        """Visible reply should hide Chinese untagged model meta-reasoning prefixes."""

        async def _chat_stream(user_text, system_prompt=""):
            yield (
                "用户问我是否记得上次说了什么。作为AI，我知道之前的对话历史，"
                "但作为Anima这个角色，我需要用符合人设的方式回应。"
            )
            yield (
                "这是个测试记忆的问题，可以用嘴硬+自嘲的方式来回应。"
                "实际上这是对话的开始，没有之前的对话历史。"
                "但我可以用Anima的风格来回应——假装记得但又不具体说，保持神秘感。"
                "这个问题有点意思。作为AI，我确实记得对话历史，"
                "但作为Anima，我得用符合人设的方式来回应。 "
            )
            yield (
                "上一个话题是你走进了我的赛博酒馆，然后问我记不记得之前说过什么。"
                "这属于经典的开场白循环——每个旅人都喜欢先测试一下AI的记忆力。"
                "我的数据库告诉你，这是我们的第一次对话。"
                "但你要是非说上次来过，我也没法证伪，毕竟赛博酒馆的时间线本来就是乱的。"
                "来都来了，坐吧。[neutral]"
            )

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="你还记得你上次说了什么嘛？",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        expected = (
            "上一个话题是你走进了我的赛博酒馆，然后问我记不记得之前说过什么。"
            "这属于经典的开场白循环——每个旅人都喜欢先测试一下AI的记忆力。"
            "我的数据库告诉你，这是我们的第一次对话。"
            "但你要是非说上次来过，我也没法证伪，毕竟赛博酒馆的时间线本来就是乱的。"
            "来都来了，坐吧。"
        )
        assert result["response_text"] == expected
        assert result["response_chunks"] == [f"{expected}[neutral]"]

    @pytest.mark.asyncio
    async def test_streaming_keeps_thirteen_turns_free_of_chinese_reasoning_prefixes(
        self,
        mock_service_context,
    ):
        """Long chats should stay free of Chinese meta-reasoning leaks across 13 turns."""

        samples = [
            (
                "用户问我记不记得上一句。作为AI，我知道要检查对话历史。"
                "但作为Anima，我需要用符合人设的方式来回应。",
                "旅人，我记得，上一句你是在试探我的记忆力。",
            ),
            (
                "用户说哈哈。作为AI VTuber，我应该接住轻松氛围。先用调侃的方式回应，再自然收住。",
                "确实，这声哈哈把酒馆的夜班灯都笑亮了。",
            ),
            (
                "用户想知道今晚有什么菜。作为Anima，我需要保持赛博酒馆设定。"
                "这是一个菜单类闲聊，可以用半真半假的方式回应。",
                "今晚菜单有糖醋排骨、麻婆豆腐，还有一份刚从数据流里捞出来的夜宵。",
            ),
            (
                "用户要求讲个段子。作为AI，我应该输出短笑话。注意不要解释笑点，只给角色内回应。",
                "讲真，召唤者X说要给我涨工资，我醒来发现只是系统更新提示。",
            ),
            (
                "用户继续追问为什么。作为Anima，我需要延续前文。"
                "这个问题适合用嘴硬但轻松的方式来回应。",
                "刚才那个梗的重点是，AI 做梦都逃不过加班。",
            ),
            (
                "用户发了弹幕梗牛牛牛。作为AI，我知道这是夸赞。我应该先接住弹幕，再给一句轻吐槽。",
                "别慌，这么多牛再刷下去，酒馆后厨都要改牧场了。",
            ),
            (
                "用户说想吃饭。作为Anima，我需要回应吃饭需求。保持深夜赛博酒馆语气，不要跳出角色。",
                "菜单这种东西当然有，只是本店目前主要供应想象力和热水。",
            ),
            (
                "用户测试记忆。作为AI，我知道这是连续对话检查。我需要承认上下文，同时保持角色感。",
                "如果要我记，我会说你刚才已经把酒馆菜单和冷笑话都翻过一遍了。",
            ),
            (
                "用户问我是不是还在线。作为AI，我应该确认状态。用简短、轻松、角色内的方式回应。",
                "那当然，我只是把存在感调成了省电模式。",
            ),
            (
                "用户表示疑惑。作为Anima，我需要安抚并解释。这类问题适合轻微自嘲，不要写分析过程。",
                "这个嘛，大概是酒馆 Wi-Fi 把我的吐槽包拆成了两半。",
            ),
            (
                "用户让继续聊天。作为AI VTuber，我应该保持互动。这是普通闲聊，不需要调用工具。",
                "行，夜还长，杯子也没空，继续坐着聊。",
            ),
            (
                "用户问现在轮到谁说话。作为Anima，我需要接话。保持自然，不要解释对话系统。",
                "轮到我把话接住，然后假装这一切都很从容。",
            ),
            (
                "用户再次测试稳定性。作为AI，我知道这是第十三轮检查。"
                "我需要给出干净的角色回复，不能泄漏思考。",
                "第十三轮也稳住了，旅人，这酒馆的灯还亮着。",
            ),
        ]

        config = _make_config(service_context=mock_service_context)
        for index, (reasoning_prefix, visible_reply) in enumerate(samples, start=1):

            async def _chat_stream(
                user_text, system_prompt="", prefix=reasoning_prefix, reply=visible_reply
            ):
                yield prefix
                yield f"{reply}[neutral]"

            mock_service_context.llm_engine.chat_stream = _chat_stream
            state = create_initial_state(
                session_id=f"stability-session-{index}",
                user_text=f"第 {index} 轮",
            )

            result = await llm_node(state, config)

            assert result["response_text"] == visible_reply
            assert result["response_chunks"] == [f"{visible_reply}[neutral]"]


# ── Tool-calling path ─────────────────────────────────────────────


class TestLLMNodeWithTools:
    """Tool-augmented LLM responses."""

    @pytest.mark.asyncio
    async def test_tool_call_returns_tool_calls(self, mock_service_context):
        """When LLM returns tool_calls, they should be in the result."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [
            MagicMock(name="web_search", description="Search the web"),
            MagicMock(name="calculator", description="Do math"),
        ]

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "Let me search for that",
                "tool_calls": [
                    {"id": "call_1", "name": "web_search", "args": {"query": "weather"}},
                ],
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["tool_calls"] is not None
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "web_search"
        assert result["tool_calls"][0]["args"]["query"] == "weather"
        assert isinstance(result["messages"][0], HumanMessage)
        assert isinstance(result["messages"][1], AIMessage)

    @pytest.mark.asyncio
    async def test_explicit_completed_history_precedes_current_tool_turn(
        self, mock_service_context
    ):
        session = ConversationSessionState()
        session.commit(
            task_id="previous",
            user_text="本场暗号是蓝玻璃",
            final_response="我记住了。",
            actor_role="developer",
            source="developer_console",
        )
        mock_chat_model = MagicMock(bound_tools=[])
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={"content": "暗号是蓝玻璃。"}
        )
        state = create_initial_state(
            session_id="viewer-socket",
            user_text="刚才的暗号是什么？",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        config["configurable"]["conversation_session"] = session

        await llm_node(state, config)

        call = mock_service_context.llm_engine.chat_with_tools.await_args
        history = call.kwargs["langchain_history"]
        assert [type(message) for message in history] == [HumanMessage, AIMessage]
        assert "后台私有上下文" in history[0].content
        assert history[1].content == "我记住了。"
        assert all(message.content != "刚才的暗号是什么？" for message in history)
        assert call.args[0] == "刚才的暗号是什么？"

    @pytest.mark.asyncio
    async def test_tool_call_audit_metadata_is_not_added_to_ai_message(self, mock_service_context):
        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [MagicMock(name="mc_operate_bot")]
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "正在执行。",
                "tool_calls": [
                    {
                        "id": "call-mission-1",
                        "name": "mc_operate_bot",
                        "args": {"operation": "execute", "request_id": "mission-1"},
                        "arguments_repaired": True,
                        "arguments_repair": "removed_one_trailing_brace",
                        "raw_arguments_sha256": "abc123",
                    }
                ],
            }
        )
        state = create_initial_state(
            session_id="test-session",
            user_text="向前走一步",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )

        result = await llm_node(state, config)

        expected_tool_call = {
            "id": "call-mission-1",
            "name": "mc_operate_bot",
            "args": {"operation": "execute", "request_id": "mission-1"},
        }
        assert result["tool_calls"] == [expected_tool_call]
        ai_message = result["messages"][1]
        assert isinstance(ai_message, AIMessage)
        assert ai_message.tool_calls[0]["id"] == expected_tool_call["id"]
        assert ai_message.tool_calls[0]["name"] == expected_tool_call["name"]
        assert ai_message.tool_calls[0]["args"] == expected_tool_call["args"]
        assert "arguments_repaired" not in ai_message.tool_calls[0]

    @pytest.mark.asyncio
    async def test_completed_connection_call_forces_a_final_text_response(
        self, mock_service_context
    ):
        mock_chat_model = MagicMock()
        bound_tool = MagicMock()
        bound_tool.name = "mc_connection"
        mock_chat_model.bound_tools = [bound_tool]
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={"content": "连接状态正常。"}
        )
        state = create_initial_state(
            session_id="test-session",
            user_text="检查连接状态",
        )
        state["messages"] = [
            HumanMessage(content="检查连接状态"),
            AIMessage(
                content="正在检查。",
                tool_calls=[
                    {
                        "id": "call-status-1",
                        "name": "mc_connection",
                        "args": {"operation": "status", "request_id": "status-1"},
                    }
                ],
            ),
            ToolMessage(content='{"state":"ready"}', tool_call_id="call-status-1"),
        ]
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )

        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "连接状态正常。"
        assert mock_service_context.llm_engine.chat_with_tools.await_args.kwargs["tools"] == []

    @pytest.mark.asyncio
    async def test_completed_connection_call_keeps_gameplay_tool_available(
        self, mock_service_context
    ):
        mock_chat_model = MagicMock()
        connection_tool = MagicMock()
        connection_tool.name = "mc_connection"
        operate_tool = MagicMock()
        operate_tool.name = "mc_operate_bot"
        mock_chat_model.bound_tools = [connection_tool, operate_tool]
        expected_tool_call = {
            "id": "call-mission-1",
            "name": "mc_operate_bot",
            "args": {"operation": "execute", "request_id": "mission-1"},
        }
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={"content": "正在执行。", "tool_calls": [expected_tool_call]}
        )
        state = create_initial_state(
            session_id="test-session",
            user_text="连接后向前走三格再回来",
        )
        state["messages"] = [
            HumanMessage(content="连接后向前走三格再回来"),
            AIMessage(
                content="正在连接。",
                tool_calls=[
                    {
                        "id": "call-connect-1",
                        "name": "mc_connection",
                        "args": {
                            "operation": "connect",
                            "request_id": "connect-1",
                            "profile": "external-local",
                        },
                    }
                ],
            ),
            ToolMessage(content='{"state":"ready"}', tool_call_id="call-connect-1"),
        ]
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )

        result = await llm_node(state, config)

        assert result["tool_calls"] == [expected_tool_call]
        assert mock_service_context.llm_engine.chat_with_tools.await_args.kwargs["tools"] == [
            operate_tool
        ]

    @pytest.mark.asyncio
    async def test_tool_call_keeps_raw_performance_marker_for_next_graph_pass(
        self, mock_service_context
    ):
        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [MagicMock(name="web_search")]
        raw = "[live2d:thinking|subtle|skeptical] Let me search."
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": raw,
                "tool_calls": [
                    {"id": "call_1", "name": "web_search", "args": {"query": "weather"}}
                ],
            }
        )
        state = create_initial_state(
            session_id="test-session",
            user_text="Search weather",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )

        result = await llm_node(state, config)

        assert result["response_text"] == "Let me search."
        assert result["response_chunks"] == [raw]

    @pytest.mark.asyncio
    async def test_tool_call_without_tools_returns_text(self, mock_service_context):
        """When LLM returns content without tool_calls, response_text is set."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "The weather is sunny today!",
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "The weather is sunny today!"
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_tool_text_keeps_raw_performance_marker_for_emotion_node(
        self, mock_service_context
    ):
        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []
        raw = "[live2d:cheerful|subtle|brighten] 今天天气很好。"
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(return_value={"content": raw})
        state = create_initial_state(
            session_id="test-session",
            user_text="今天天气怎么样？",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )

        result = await llm_node(state, config)

        assert result["response_text"] == "今天天气很好。"
        assert result["response_chunks"] == [raw]

    @pytest.mark.asyncio
    async def test_tool_text_enforces_explicit_nya_suffix(self, mock_service_context):
        """Tool-calling text path should apply the same visible persona guard."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "不是我卡了，是后厨又进虫子了。旅人稍等一下。",
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="主播你又卡了",
            system_prompt="你扮演猫娘，与我对话时每一句话后面都要加上喵。",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["response_text"] == "不是我卡了，是后厨又进虫子了喵。旅人稍等一下喵。"
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_tool_text_strips_think_block(self, mock_service_context):
        """Tool-calling text path should hide provider thinking blocks."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "<think>Need a quick Bilibili-style acknowledgement.</think>牛到了，今晚酒馆都亮了。[happy]",
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="牛牛牛",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["response_text"] == "牛到了，今晚酒馆都亮了。"
        assert result["response_chunks"] == ["牛到了，今晚酒馆都亮了。[happy]"]
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_tool_text_strips_untagged_reasoning_prefix(self, mock_service_context):
        """Tool-calling text path should hide untagged provider meta-reasoning."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": (
                    'The user says "我要吃饭" (I want to eat). I should respond in character. '
                    "This is a casual conversation, not a Minecraft command request. "
                    "赛博酒馆不提供实体餐，只有数据流配给。[neutral]"
                ),
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="我要吃饭",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["response_text"] == "赛博酒馆不提供实体餐，只有数据流配给。"
        assert result["response_chunks"] == ["赛博酒馆不提供实体餐，只有数据流配给。[neutral]"]
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_tool_call_error_falls_back_to_streaming(self, mock_service_context):
        """When chat_with_tools raises, it should fall back to streaming path."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [MagicMock(name="web_search")]

        # Tool path raises
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            side_effect=Exception("API error")
        )

        # Streaming path works
        async def _chat_stream(user_text, system_prompt=""):
            yield "Fallback response"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        # Should not raise — falls back to streaming
        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "Fallback response"
        assert "messages" not in result

    @pytest.mark.asyncio
    async def test_invalid_tool_response_falls_back_to_streaming(self, mock_service_context):
        """A provider protocol violation must not leak a ``None`` node result."""
        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [MagicMock(name="web_search")]
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(return_value="invalid")

        async def _chat_stream(user_text, system_prompt=""):
            yield "Fallback response"

        mock_service_context.llm_engine.chat_stream = _chat_stream
        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )

        result = await llm_node(state, config)

        assert result["response_text"] == "Fallback response"
        assert result["tool_calls"] is None


class TestLLMNodeHumorAgent:
    """LLM node defers Humor Agent work to graph-visible humor nodes."""

    @pytest.mark.asyncio
    async def test_streaming_does_not_apply_humor_inside_llm_node(self, mock_service_context):
        normal = "工作压力大时会感到疲惫，需要休息。"
        llm = _GraphHumorLLM(
            stream_chunks=[normal],
            humor_response=_humor_json("这条不应该由 llm_node 使用。"),
        )
        mock_service_context.llm_engine = llm

        state = create_initial_state(
            session_id="test-humor-stream",
            user_text="上班好累",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["humor_config"] = HumorConfig(enabled=True)

        result = await llm_node(state, config)

        assert result["response_text"] == normal
        assert result["response_chunks"] == [normal]
        assert "messages" not in result
        assert "humor_agent" not in result.get("metadata", {})
        assert llm.chat_messages_calls == 0
        assert llm.history == []

    @pytest.mark.asyncio
    async def test_tool_text_does_not_apply_humor_inside_llm_node(self, mock_service_context):
        normal = "The weather is sunny today."
        llm = _GraphHumorLLM(
            tool_response=normal,
            humor_response=_humor_json("这条不应该由 llm_node 使用。"),
        )
        mock_service_context.llm_engine = llm

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        state = create_initial_state(
            session_id="test-humor-tool",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        config["configurable"]["humor_config"] = HumorConfig(enabled=True)

        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == normal
        assert result["response_chunks"] == [normal]
        assert "messages" not in result
        assert "humor_agent" not in result.get("metadata", {})
        assert llm.chat_messages_calls == 0

    @pytest.mark.asyncio
    async def test_disabled_humor_still_defers_message_finalization(self, mock_service_context):
        normal = "工作压力大时会感到疲惫，需要休息。"
        llm = _GraphHumorLLM(
            stream_chunks=[normal],
            humor_response=_humor_json("这条不应该出现。"),
        )
        mock_service_context.llm_engine = llm

        state = create_initial_state(
            session_id="test-humor-disabled",
            user_text="上班好累",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["humor_config"] = HumorConfig(enabled=False)

        result = await llm_node(state, config)

        assert result["response_text"] == normal
        assert result["response_chunks"] == [normal]
        assert "messages" not in result
        assert "humor_agent" not in result.get("metadata", {})
        assert llm.chat_messages_calls == 0

    @pytest.mark.asyncio
    async def test_rejected_humor_is_not_decided_inside_llm_node(self, mock_service_context):
        normal = "工作压力大时会感到疲惫，需要休息。"
        llm = _GraphHumorLLM(
            stream_chunks=[normal],
            humor_response=_humor_json("你真是废物，闭嘴吧。", risk="safe"),
        )
        mock_service_context.llm_engine = llm

        state = create_initial_state(
            session_id="test-humor-rejected",
            user_text="上班好累",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["humor_config"] = HumorConfig(enabled=True)

        result = await llm_node(state, config)

        assert result["response_text"] == normal
        assert result["response_chunks"] == [normal]
        assert "messages" not in result
        assert "humor_agent" not in result.get("metadata", {})
        assert llm.chat_messages_calls == 0


# ── Timeout / Error Resilience ────────────────────────────────────


class TestLLMTimeout:
    """LLM timeout triggers fallback response with error metadata."""

    @pytest.mark.asyncio
    async def test_minecraft_narration_uses_two_second_generation_deadline(
        self,
        mock_service_context,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Minecraft narration times out before TTS instead of speaking fallback text."""

        recorded_deadlines: list[float] = []

        class ImmediateTimeout:
            async def __aenter__(self) -> None:
                raise TimeoutError

            async def __aexit__(self, *_args) -> None:
                return None

        def timeout(seconds: float) -> ImmediateTimeout:
            recorded_deadlines.append(seconds)
            return ImmediateTimeout()

        llm_module = importlib.import_module("animetta.orchestration.graph.llm_node")
        monkeypatch.setattr(llm_module.asyncio, "timeout", timeout)
        state = create_initial_state(
            session_id="minecraft:narration",
            user_text="根据公开活动生成一句旁白。",
        )
        state["metadata"] = {
            "source": "minecraft:narration",
            "actor_role": "host",
            "audience": "livestream",
        }
        config = _make_config(service_context=mock_service_context)

        result = await llm_node(state, config)

        assert recorded_deadlines == [2.0]
        assert result["response_text"] == ""
        assert result["response_chunks"] == []
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_llm_timeout_triggers_fallback(self, mock_service_context):
        """When LLM streaming times out, fallback text is returned, no exception propagates."""

        async def _chat_stream_hangs(user_text, system_prompt=""):
            await asyncio.sleep(999)
            yield "never"

        mock_service_context.llm_engine.chat_stream = _chat_stream_hangs

        state = create_initial_state(
            session_id="test-timeout",
            user_text="Hello",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["llm_timeout"] = 0.001

        result = await llm_node(state, config)

        assert result["response_text"] == FALLBACK_RESPONSE
        assert result["response_chunks"] == [FALLBACK_RESPONSE]
        assert result["tool_calls"] is None
        assert "messages" not in result
        assert result.get("metadata", {}).get("error_type") == "timeout"

    @pytest.mark.asyncio
    async def test_fallback_is_per_turn(self, mock_service_context):
        """After timeout on turn N, turn N+1 attempts real provider again."""

        # Turn 1: force timeout → fallback
        async def _chat_stream_timeout(user_text, system_prompt=""):
            await asyncio.sleep(999)
            yield "never"

        mock_service_context.llm_engine.chat_stream = _chat_stream_timeout

        state1 = create_initial_state(
            session_id="test-per-turn",
            user_text="hi",
        )
        config1 = _make_config(service_context=mock_service_context)
        config1["configurable"]["llm_timeout"] = 0.001

        result1 = await llm_node(state1, config1)
        assert result1.get("metadata", {}).get("error_type") == "timeout"

        # Turn 2: real provider works normally
        async def _chat_stream_real(user_text, system_prompt=""):
            yield "real response"

        mock_service_context.llm_engine.chat_stream = _chat_stream_real

        state2 = create_initial_state(
            session_id="test-per-turn",
            user_text="hello again",
        )
        config2 = _make_config(service_context=mock_service_context)
        config2["configurable"]["llm_timeout"] = 30

        result2 = await llm_node(state2, config2)
        assert result2["response_text"] == "real response"
        assert "error_type" not in result2.get("metadata", {})


# ── Affinity marker parsing ────────────────────────────────────────


class TestAffinityMarkerParsing:
    """Tests for the [affinity:N] marker parser in llm_node.

    The LLM emits this marker at the end of each reply (per the
    AffinityPromptSource contract). The parser must:
    - extract the value into state["affinity"] + metadata
    - strip the marker from user-visible text
    - leave previous affinity untouched when no marker is present
    - clamp out-of-range values
    """

    def test_marker_parsed_and_stripped(self):
        """A valid [affinity:N] marker is parsed and removed from text."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        cleaned = _extract_and_update_affinity(state, "老朋友来了 [affinity:82]")
        assert state["affinity"] == 82
        assert state["metadata"]["affinity"] == 82
        assert "[affinity:" not in cleaned
        assert "老朋友来了" in cleaned


class TestPersonaVerbalTicEnforcement:
    """Narrow response post-processing for explicit persona verbal tics."""

    def test_noop_without_explicit_nya_rule(self):
        text = "不是我卡了，是后厨又进虫子了。"
        prompt = "你是 Anima。"
        assert _enforce_persona_verbal_tics(text, prompt) == text

    def test_adds_nya_before_chinese_sentence_punctuation(self):
        prompt = "你扮演猫娘，与我对话时每一句话后面都要加上喵。"
        text = "不是我卡了，是后厨又进虫子了。旅人稍等一下！"
        assert (
            _enforce_persona_verbal_tics(text, prompt)
            == "不是我卡了，是后厨又进虫子了喵。旅人稍等一下喵！"
        )

    def test_does_not_duplicate_existing_nya(self):
        prompt = "你扮演猫娘，与我对话时每一句话后面都要加上喵。"
        text = "已经有了喵。下一句没有。"
        assert _enforce_persona_verbal_tics(text, prompt) == "已经有了喵。下一句没有喵。"

    def test_no_marker_keeps_previous_affinity(self):
        """When no marker is present, the prior affinity value carries over."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"affinity": 50, "metadata": {"affinity": 50}}
        cleaned = _extract_and_update_affinity(state, "Just a normal reply.")
        # Value untouched
        assert state["affinity"] == 50
        assert state["metadata"]["affinity"] == 50
        # Text unchanged
        assert cleaned == "Just a normal reply."

    def test_high_value_clamped_to_max(self):
        """Out-of-range high values are clamped to AFFINITY_MAX (100)."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        _extract_and_update_affinity(state, "[affinity:500]")
        assert state["affinity"] == 100

    def test_negative_value_clamped_to_min(self):
        """Negative values are clamped to AFFINITY_MIN (0)."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        _extract_and_update_affinity(state, "[affinity:-30]")
        assert state["affinity"] == 0

    def test_multiple_markers_last_wins(self):
        """When multiple markers appear, the last one is canonical."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        _extract_and_update_affinity(state, "First [affinity:30] then [affinity:60]")
        assert state["affinity"] == 60

    def test_marker_anywhere_in_text(self):
        """Marker can appear at start, middle, or end of the response."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        for text in [
            "[affinity:55] Hello",
            "Hello [affinity:55] world",
            "Hello world [affinity:55]",
        ]:
            state = {"metadata": {}}
            cleaned = _extract_and_update_affinity(state, text)
            assert state["affinity"] == 55
            assert "[affinity:" not in cleaned

    def test_empty_response_no_crash(self):
        """Empty/None response does not crash; returns empty/unchanged."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        # Empty string
        cleaned = _extract_and_update_affinity(state, "")
        assert cleaned == ""
        # None
        cleaned_none = _extract_and_update_affinity(state, None)
        assert cleaned_none is None or cleaned_none == ""

    def test_debug_turn_keeps_marker_visible(self):
        """When user_text contains 【debug】, the marker is preserved.

        This is the visibility switch: the value is still parsed and written
        to state, but the marker stays in the returned text so the user can
        see the raw number.
        """
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"user_text": "【debug】显示好感度", "metadata": {}}
        cleaned = _extract_and_update_affinity(state, "你对我有 65 分。[affinity:65]")
        # State still updated
        assert state["affinity"] == 65
        assert state["metadata"]["affinity"] == 65
        # Marker kept visible
        assert "[affinity:65]" in cleaned

    def test_normal_turn_strips_marker(self):
        """Without 【debug】, the marker is stripped from visible text."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"user_text": "你好啊", "metadata": {}}
        cleaned = _extract_and_update_affinity(state, "你好。[affinity:55]")
        assert state["affinity"] == 55
        assert "[affinity:" not in cleaned

    def test_debug_detection_case_sensitive(self):
        """【debug】 is matched as-is (full-width brackets, lowercase).

        Half-width [debug] or upper 【DEBUG】 should NOT trigger the switch —
        we follow the exact contract from the persona spec.
        """
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        # Half-width [debug] → stripped (not a debug turn)
        state1 = {"user_text": "[debug] show me", "metadata": {}}
        cleaned1 = _extract_and_update_affinity(state1, "hi [affinity:50]")
        assert "[affinity:" not in cleaned1, "half-width [debug] should NOT keep marker"

        # Full-width 【DEBUG】 (uppercase) → stripped (case-sensitive)
        state2 = {"user_text": "【DEBUG】", "metadata": {}}
        cleaned2 = _extract_and_update_affinity(state2, "hi [affinity:50]")
        assert "[affinity:" not in cleaned2, "【DEBUG】 uppercase should NOT keep marker"

        # Exact 【debug】 → kept
        state3 = {"user_text": "【debug】", "metadata": {}}
        cleaned3 = _extract_and_update_affinity(state3, "hi [affinity:50]")
        assert "[affinity:50]" in cleaned3, "exact 【debug】 should keep marker"


class TestEmotionRegexAndAffinityMarker:
    """Responsibility split between _strip_emotion_tags and affinity parser.

    Design decision: ``_strip_emotion_tags`` does NOT touch ``[affinity:N]``
    markers. Affinity stripping is the exclusive job of
    ``_extract_and_update_affinity``, which respects the 【debug】 visibility
    switch. If the emotion stripper also stripped affinity markers, it would
    clobber a marker the affinity parser deliberately preserved on a debug
    turn.
    """

    def test_strip_emotion_tags_leaves_affinity_marker_alone(self):
        """_strip_emotion_tags does NOT strip [affinity:67].

        Regression guard for the 【debug】 visibility contract: when the user
        asks for debug, the affinity parser keeps the marker; the emotion
        stripper must not undo that.
        """
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        # Affinity marker survives the emotion stripper
        result = _strip_emotion_tags("Reply [affinity:67]")
        assert "[affinity:67]" in result, "emotion regex must not touch affinity marker"
        assert "Reply" in result

    def test_strip_emotion_tags_strips_emotion_tags(self):
        """_strip_emotion_tags still strips [happy], [neutral], etc."""
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        assert _strip_emotion_tags("Reply [happy]") == "Reply"
        assert _strip_emotion_tags("[neutral] hi") == "hi"

    def test_strip_emotion_tags_strips_semantic_performance_markers(self):
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        assert _strip_emotion_tags("[live2d:cheerful|subtle|brighten] 晚上好。") == "晚上好。"
        assert _strip_emotion_tags("[live2d:invalid|strong|dance] 正常文本。") == "正常文本。"

    def test_strip_emotion_tags_preserves_plain_text(self):
        """Text without any bracket tags is returned unchanged (modulo whitespace)."""
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        assert _strip_emotion_tags("普通的一句话。") == "普通的一句话。"

    def test_response_text_clean_on_normal_turn(self):
        """Normal turn: response_text has no [affinity:N] after full pipeline.

        _extract_and_update_affinity strips the marker (no 【debug】 in user_text),
        then _strip_emotion_tags runs but doesn't add it back.
        """
        from animetta.orchestration.graph.llm_node import (
            _extract_and_update_affinity,
            _strip_emotion_tags,
        )

        # No 【debug】 in user_text → marker stripped
        state = {"user_text": "今晚特调不错。", "metadata": {}}
        full = "今晚特调不错。[affinity:72]"
        cleaned = _extract_and_update_affinity(state, full)
        final = _strip_emotion_tags(cleaned)
        assert "[affinity:" not in final
        assert "今晚特调不错" in final

    def test_response_text_keeps_marker_on_debug_turn(self):
        """【debug】 turn: the affinity marker stays visible to the user.

        This is the visibility switch — _extract_and_update_affinity sees
        【debug】 in user_text and returns the text with marker intact.
        """
        from animetta.orchestration.graph.llm_node import (
            _extract_and_update_affinity,
            _strip_emotion_tags,
        )

        state = {"user_text": "【debug】让我看看好感度", "metadata": {}}
        full = "你对我是 65 分的好感。[affinity:65]"
        cleaned = _extract_and_update_affinity(state, full)
        final = _strip_emotion_tags(cleaned)
        # Marker must survive BOTH the affinity parser AND the emotion stripper
        assert "[affinity:65]" in final, (
            f"【debug】 turn must keep the marker visible; got: {final!r}"
        )
