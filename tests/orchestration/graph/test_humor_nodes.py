from __future__ import annotations

"""Tests for graph-visible Humor Agent rewrite and validation nodes."""

import json
import time

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import RunnableConfig

from animetta.orchestration.graph.humor_rewrite_node import humor_rewrite_node
from animetta.orchestration.graph.humor_validation_node import humor_validation_node
from animetta.orchestration.graph.state import create_initial_state
from animetta.services.humor import HumorConfig
from animetta.services.humor.metadata import (
    HUMOR_AGENT_KEY,
    HUMOR_CANDIDATE_KEY,
    HUMOR_VALIDATION_KEY,
    record_humor_candidate,
)
from animetta.services.humor.models import HumorRewriteRequest
from animetta.services.humor.parser import parse_humor_result


def _humor_json(candidate: str = "幽默回复", *, risk: str = "safe") -> str:
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


def _make_state(response_text: str = "普通回复", **overrides):
    state = create_initial_state(session_id="test-humor-node", user_text="上班好累")
    state["response_text"] = response_text
    state["response_chunks"] = [response_text] if response_text else []
    state.update(overrides)
    return state


def _make_config(service_context, humor_config: HumorConfig | None = None):
    return RunnableConfig(
        configurable={
            "service_context": service_context,
            "humor_config": humor_config or HumorConfig(enabled=True),
        }
    )


class _HumorNodeLLM:
    def __init__(self, response: str | None = None, history_response: str = "普通回复") -> None:
        self.response = response or _humor_json()
        self.chat_messages_calls = 0
        self.history = [
            {"role": "user", "content": "上班好累"},
            {"role": "assistant", "content": history_response},
        ]

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self.chat_messages_calls += 1
        self.last_messages = messages
        return self.response

    def get_history(self) -> list[dict]:
        return [msg.copy() for msg in self.history]

    def clear_history(self) -> None:
        self.history.clear()


class _ServiceContext:
    def __init__(self, llm_engine=None, app_config=None) -> None:
        self.llm_engine = llm_engine
        self.config = app_config


def _candidate_metadata(normal: str = "普通回复", candidate: str = "幽默回复"):
    request = HumorRewriteRequest(
        user_input="上班好累",
        normal_response=normal,
        persona={"name": "Anima"},
        config=HumorConfig(enabled=True),
    )
    result = parse_humor_result(_humor_json(candidate), request)
    return record_humor_candidate({}, result)


class TestHumorRewriteNode:
    @pytest.mark.asyncio
    async def test_disabled_config_preserves_response_without_llm_call(self):
        llm = _HumorNodeLLM()
        state = _make_state("普通回复")
        config = _make_config(
            _ServiceContext(llm),
            HumorConfig(enabled=False),
        )

        result = await humor_rewrite_node(state, config)

        assert result["response_text"] == "普通回复"
        assert result["response_chunks"] == ["普通回复"]
        assert HUMOR_AGENT_KEY not in result.get("metadata", {})
        assert llm.chat_messages_calls == 0

    @pytest.mark.asyncio
    async def test_missing_llm_engine_preserves_response(self):
        state = _make_state("普通回复")
        config = _make_config(_ServiceContext(None), HumorConfig(enabled=True))

        result = await humor_rewrite_node(state, config)

        assert result["response_text"] == "普通回复"
        assert result["response_chunks"] == ["普通回复"]
        assert HUMOR_AGENT_KEY not in result.get("metadata", {})

    @pytest.mark.asyncio
    async def test_successful_generation_records_candidate_without_replacing_response(self):
        llm = _HumorNodeLLM(response=_humor_json("幽默回复"))
        state = _make_state("普通回复")
        config = _make_config(_ServiceContext(llm), HumorConfig(enabled=True))

        result = await humor_rewrite_node(state, config)

        assert result["response_text"] == "普通回复"
        assert result["response_chunks"] == ["普通回复"]
        assert result["metadata"][HUMOR_AGENT_KEY]["accepted"] is False
        assert result["metadata"][HUMOR_AGENT_KEY]["fallback_reason"] is None
        assert result["metadata"][HUMOR_CANDIDATE_KEY]["candidate_response"] == "幽默回复"

    @pytest.mark.asyncio
    async def test_generation_fallback_records_reason_without_candidate(self):
        llm = _HumorNodeLLM(response="not json")
        state = _make_state("普通回复")
        config = _make_config(_ServiceContext(llm), HumorConfig(enabled=True))

        result = await humor_rewrite_node(state, config)

        assert result["response_text"] == "普通回复"
        assert result["metadata"][HUMOR_AGENT_KEY]["accepted"] is False
        assert result["metadata"][HUMOR_AGENT_KEY]["fallback_reason"] == "invalid_json"
        assert HUMOR_CANDIDATE_KEY not in result["metadata"]

    async def test_active_scene_guidance_bypasses_humor_llm(self):
        llm = _HumorNodeLLM(response=_humor_json("不该生成"))
        state = _make_state(
            "普通回复",
            metadata={
                "scene_guidance": {
                    "scene_revision": 1,
                    "scene_summary": "当前笑点正在上升。",
                    "response_objective": "接住当前笑点。",
                    "tone": ["playful"],
                    "confidence": 0.9,
                    "expires_at": time.time() + 60,
                }
            },
        )
        config = _make_config(_ServiceContext(llm), HumorConfig(enabled=True))

        result = await humor_rewrite_node(state, config)

        assert result["response_text"] == "普通回复"
        assert result["metadata"]["scene_guidance"]["scene_revision"] == 1
        assert HUMOR_CANDIDATE_KEY not in result["metadata"]
        assert llm.chat_messages_calls == 0


class TestHumorValidationNode:
    @pytest.mark.asyncio
    async def test_accepted_candidate_replaces_response_without_mutating_provider_history(self):
        normal = "普通回复"
        candidate = "幽默回复"
        llm = _HumorNodeLLM(history_response=normal)
        state = _make_state(normal, metadata=_candidate_metadata(normal, candidate))
        config = _make_config(_ServiceContext(llm), HumorConfig(enabled=True))

        result = await humor_validation_node(state, config)

        assert result["response_text"] == candidate
        assert result["response_chunks"] == [candidate]
        assert result["messages"] == [AIMessage(content=candidate)]
        assert result["metadata"][HUMOR_AGENT_KEY]["accepted"] is True
        assert result["metadata"][HUMOR_VALIDATION_KEY]["accepted"] is True
        assert llm.history[-1]["content"] == normal

    @pytest.mark.asyncio
    async def test_rejected_candidate_preserves_normal_response(self):
        normal = "普通回复"
        metadata = _candidate_metadata(normal, "你真是废物，闭嘴吧。")
        state = _make_state(normal, metadata=metadata)
        config = _make_config(_ServiceContext(_HumorNodeLLM()), HumorConfig(enabled=True))

        result = await humor_validation_node(state, config)

        assert result["response_text"] == normal
        assert result["response_chunks"] == [normal]
        assert result["messages"] == [AIMessage(content=normal)]
        assert result["metadata"][HUMOR_AGENT_KEY]["accepted"] is False
        assert (
            result["metadata"][HUMOR_VALIDATION_KEY]["fallback_reason"]
            == "hostile_viewer_targeting"
        )

    @pytest.mark.asyncio
    async def test_missing_candidate_finalizes_normal_message_once(self):
        normal = "普通回复"
        state = _make_state(normal, metadata={})
        config = _make_config(_ServiceContext(_HumorNodeLLM()), HumorConfig(enabled=False))

        result = await humor_validation_node(state, config)

        assert result["response_text"] == normal
        assert result["response_chunks"] == [normal]
        assert result["messages"] == [AIMessage(content=normal)]
        assert HUMOR_VALIDATION_KEY not in result.get("metadata", {})
