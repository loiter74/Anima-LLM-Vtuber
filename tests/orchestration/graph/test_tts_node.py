from __future__ import annotations

"""Tests for TTS synthesis node."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.types import RunnableConfig

from animetta.observability.service_proxy import instrument_service
from animetta.orchestration.graph import tts_node
from animetta.orchestration.graph.state import create_initial_state
from animetta.services.tts.mock_tts import MockTTS
from animetta.services.tts.remote_tts import RemoteTTS, RemoteTTSUpstreamError

_tts_node_module = sys.modules["animetta.orchestration.graph.tts_node"]


class TestTTSNode:
    """TTS node: text-to-speech synthesis."""

    def _make_state(session_id="test", response_text=""):
        state = create_initial_state(session_id=session_id)
        state["response_text"] = response_text
        return state

    @pytest.mark.asyncio
    async def test_empty_text_skips_tts(self):
        """Empty response_text should skip TTS and return None."""

        state = self._make_state(response_text="")
        result = await tts_node(state)
        assert result["tts_audio"] is None
        assert result["media_status"].status == "skipped"

    @pytest.mark.asyncio
    async def test_no_service_context_returns_error(self):
        """Missing service_context returns error."""

        state = self._make_state(response_text="Hello world")
        config = RunnableConfig(configurable={})
        result = await tts_node(state, config)
        assert result.get("error") is not None
        assert result["tts_audio"] is None

    @pytest.mark.asyncio
    async def test_no_tts_engine_skips(self, mock_service_context):
        """Service context without tts_engine skips TTS."""

        ctx = mock_service_context
        ctx.tts_engine = None

        state = self._make_state(response_text="Hello world")
        config = RunnableConfig(configurable={"service_context": ctx})
        result = await tts_node(state, config)
        assert result["tts_audio"] is None

    @pytest.mark.asyncio
    async def test_synthesize_returns_audio_bytes(self, mock_service_context):
        """TTS engine returns audio bytes, stored in state."""

        mock_service_context.tts_engine.synthesize = AsyncMock(return_value=b"fake_audio_bytes")

        state = self._make_state(response_text="Hello world")
        config = RunnableConfig(configurable={"service_context": mock_service_context})
        result = await tts_node(state, config)
        assert result["tts_audio"] == b"fake_audio_bytes"
        assert result["media_status"].status == "ready"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "outcome,reason",
        [
            (b"", "empty_audio"),
            (None, "empty_audio"),
        ],
    )
    async def test_golden_empty_audio_is_typed_degradation(
        self, mock_service_context, outcome, reason
    ):
        mock_service_context.config = SimpleNamespace(
            system=SimpleNamespace(runtime_profile="golden", golden_tts_timeout_seconds=20.0)
        )
        mock_service_context.tts_engine.synthesize = AsyncMock(return_value=outcome)
        result = await tts_node(
            self._make_state(response_text="你好"),
            RunnableConfig(configurable={"service_context": mock_service_context}),
        )
        assert result["tts_audio"] is None
        assert result["media_status"].status == "degraded"
        assert result["media_status"].reason == reason

    @pytest.mark.asyncio
    async def test_golden_exception_is_per_turn_and_next_call_recovers(self, mock_service_context):
        mock_service_context.config = SimpleNamespace(
            system=SimpleNamespace(runtime_profile="golden", golden_tts_timeout_seconds=20.0)
        )
        mock_service_context.tts_engine.synthesize = AsyncMock(
            side_effect=[RuntimeError("rate limit"), b"RIFFaudio"]
        )
        config = RunnableConfig(configurable={"service_context": mock_service_context})
        first = await tts_node(self._make_state(response_text="第一轮"), config)
        second = await tts_node(self._make_state(response_text="第二轮"), config)
        assert first["media_status"].status == "degraded"
        assert first["tts_audio"] is None
        assert second["media_status"].status == "ready"
        assert second["tts_audio"] == b"RIFFaudio"

    @pytest.mark.asyncio
    async def test_golden_timeout_uses_configured_bound(self, mock_service_context, monkeypatch):
        mock_service_context.config = SimpleNamespace(
            system=SimpleNamespace(runtime_profile="golden", golden_tts_timeout_seconds=7.0)
        )
        mock_service_context.tts_engine.synthesize = AsyncMock(return_value=b"unused")
        observed: list[float] = []

        async def wait_for(awaitable, *, timeout):
            observed.append(timeout)
            awaitable.close()
            raise TimeoutError

        monkeypatch.setattr(_tts_node_module.asyncio, "wait_for", wait_for)
        result = await tts_node(
            self._make_state(response_text="你好"),
            RunnableConfig(configurable={"service_context": mock_service_context}),
        )
        assert observed == [7.0]
        assert result["media_status"].reason == "timeout"

    @pytest.mark.asyncio
    async def test_production_remote_failure_preserves_text_and_retries_same_voice_next_turn(
        self, mock_service_context
    ):
        mock_service_context.config = SimpleNamespace(
            system=SimpleNamespace(
                runtime_profile="production",
                golden_tts_timeout_seconds=20.0,
            )
        )
        engine = mock_service_context.tts_engine
        engine.synthesize = AsyncMock(
            side_effect=[
                RemoteTTSUpstreamError(
                    "Remote TTS request failed",
                    category="busy",
                    request_id="first",
                    retryable=True,
                    status_code=429,
                ),
                b"RIFF-alice",
            ]
        )
        first_state = self._make_state(response_text="第一轮文字仍然保留")
        first_state["live2d_emotion"] = "happy"
        second_state = self._make_state(response_text="第二轮继续 Alice")
        config = RunnableConfig(configurable={"service_context": mock_service_context})

        first = await tts_node(first_state, config)
        second = await tts_node(second_state, config)

        assert first_state["response_text"] == "第一轮文字仍然保留"
        assert first_state["live2d_emotion"] == "happy"
        assert first["tts_audio"] is None
        assert first["media_status"].reason == "busy"
        assert first["media_status"].retryable is True
        assert first["metadata"]["degradation_reason"] == "busy"
        assert second["tts_audio"] == b"RIFF-alice"
        assert mock_service_context.tts_engine is engine
        assert engine.synthesize.await_count == 2

    @staticmethod
    def _production_context(tts_engine):
        configured = SimpleNamespace(
            type="remote",
            model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            voice="alice",
            public_identity=lambda: {
                "type": "remote",
                "provider": "qwen3",
                "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                "voice": "alice",
            },
        )
        return SimpleNamespace(
            tts_engine=tts_engine,
            config=SimpleNamespace(
                system=SimpleNamespace(
                    runtime_profile="production",
                    golden_tts_timeout_seconds=20.0,
                ),
                providers={"tts": configured},
            ),
        )

    @pytest.mark.asyncio
    async def test_instrumented_remote_reports_resolved_provider_not_wrapper_name(self):
        target = RemoteTTS(
            api_key="test",
            base_url="http://qwen-tts:8766",
            provider="qwen3",
            model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            voice="alice",
            response_format="wav",
            language="Chinese",
            timeout_seconds=20.0,
            revision="revision",
        )
        target.synthesize = AsyncMock(return_value=b"RIFF-alice")  # type: ignore[method-assign]
        engine = instrument_service(
            target,
            None,
            "tts",
            provider="remote",
            model=target.model,
        )
        context = self._production_context(engine)

        result = await tts_node(
            self._make_state(response_text="你好"),
            RunnableConfig(configurable={"service_context": context}),
        )

        assert result["media_status"].provider == "qwen3"
        assert result["metadata"]["tts_provider"] == "qwen3"
        assert "Proxy" not in result["metadata"]["tts_provider"]

    @pytest.mark.asyncio
    async def test_instrumented_mock_is_forbidden_in_production(self):
        target = MockTTS()
        target.synthesize = AsyncMock(return_value=b"should-not-run")  # type: ignore[method-assign]
        engine = instrument_service(target, None, "tts", provider="mock", model="mock")
        context = self._production_context(engine)

        result = await tts_node(
            self._make_state(response_text="你好"),
            RunnableConfig(configurable={"service_context": context}),
        )

        assert result["tts_audio"] is None
        assert result["media_status"].reason == "mock_forbidden"
        target.synthesize.assert_not_awaited()  # type: ignore[attr-defined]
