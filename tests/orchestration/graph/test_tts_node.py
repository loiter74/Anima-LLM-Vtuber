from __future__ import annotations

"""Tests for TTS synthesis node."""

import asyncio
import base64
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.types import RunnableConfig

from animetta.observability.service_proxy import instrument_service
from animetta.orchestration.graph import tts_node
from animetta.orchestration.graph.interrupt_handler import get_interrupt_handler
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

    @pytest.mark.parametrize(
        ("emotion", "modifier"),
        [
            ("neutral", "平稳"),
            ("happy", "轻微上扬"),
            ("sad", "放慢"),
            ("angry", "压低"),
            ("surprised", "短暂停顿"),
            ("thinking", "思考停顿"),
        ],
    )
    async def test_emotion_aware_engine_receives_character_bounded_instruction(
        self,
        mock_service_context,
        emotion: str,
        modifier: str,
    ) -> None:
        engine = mock_service_context.tts_engine
        engine.supports_emotion_instructions = True
        engine.synthesize = AsyncMock(return_value=b"RIFFaudio")
        state = self._make_state(response_text="这是一条需要合成的回复。")
        state["emotion"] = emotion

        await tts_node(
            state,
            RunnableConfig(configurable={"service_context": mock_service_context}),
        )

        kwargs = engine.synthesize.await_args.kwargs
        assert kwargs["emotion"] == emotion
        assert modifier in kwargs["instruction"]
        for constraint in ("冷静", "克制", "有教养", "不卖萌", "不夸张"):
            assert constraint in kwargs["instruction"]

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


class TestStreamingTTSNode:
    @staticmethod
    def _state(emotion: str = "thinking"):
        state = create_initial_state(session_id="socket-1")
        state["response_text"] = "让我认真想一想。"
        state["emotion"] = emotion
        return state

    @staticmethod
    def _config(
        engine,
        socket: AsyncMock,
        *,
        runtime_profile: str = "development",
        timeout_seconds: float = 20.0,
    ) -> RunnableConfig:
        context = SimpleNamespace(
            tts_engine=engine,
            config=SimpleNamespace(
                system=SimpleNamespace(
                    runtime_profile=runtime_profile,
                    golden_tts_timeout_seconds=timeout_seconds,
                )
            ),
        )
        return RunnableConfig(configurable={"service_context": context, "socketio": socket})

    @pytest.mark.asyncio
    async def test_emits_start_ordered_chunks_and_completed_end(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                assert kwargs["emotion"] == "thinking"
                yield b"\x00\x01"
                yield b"\x02\x03"

        socket = AsyncMock()
        result = await tts_node(self._state(), self._config(Engine(), socket))

        calls = socket.emit.await_args_list
        assert [call.args[0] for call in calls] == [
            "chat:audio_stream_start",
            "chat:audio_stream_chunk",
            "chat:audio_stream_chunk",
            "chat:audio_stream_end",
        ]
        assert [call.args[1].get("sequence") for call in calls[1:3]] == [0, 1]
        assert base64.b64decode(calls[1].args[1]["audio_data"]) == b"\x00\x01"
        assert base64.b64decode(calls[2].args[1]["audio_data"]) == b"\x02\x03"
        assert calls[3].args[1]["status"] == "completed"
        assert calls[3].args[1]["final_sequence"] == 1
        assert result["tts_audio"] is None
        assert result["media_status"].status == "ready"
        assert result["metadata"]["audio_streamed"] is True

    @pytest.mark.asyncio
    async def test_retries_once_before_first_chunk_with_same_instruction(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                self.calls.append(dict(kwargs))
                if len(self.calls) == 1:
                    raise RuntimeError("connection dropped before audio")
                yield b"\x00\x01"

        engine = Engine()
        socket = AsyncMock()
        result = await tts_node(self._state("sad"), self._config(engine, socket))

        assert len(engine.calls) == 2
        assert engine.calls[0] == engine.calls[1]
        assert [call.args[0] for call in socket.emit.await_args_list] == [
            "chat:audio_stream_start",
            "chat:audio_stream_chunk",
            "chat:audio_stream_end",
        ]
        assert result["media_status"].status == "ready"

    @pytest.mark.asyncio
    async def test_failure_after_first_chunk_ends_stream_without_retry(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.calls = 0

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                self.calls += 1
                yield b"\x00\x01"
                raise RuntimeError("connection dropped after audio")

        engine = Engine()
        socket = AsyncMock()
        state = self._state("angry")
        result = await tts_node(state, self._config(engine, socket))

        assert engine.calls == 1
        assert state["response_text"] == "让我认真想一想。"
        assert [call.args[0] for call in socket.emit.await_args_list] == [
            "chat:audio_stream_start",
            "chat:audio_stream_chunk",
            "chat:audio_stream_end",
        ]
        assert socket.emit.await_args_list[-1].args[1]["status"] == "failed"
        assert result["tts_audio"] is None
        assert result["media_status"].status == "degraded"

    @pytest.mark.asyncio
    async def test_timeout_before_first_chunk_retries_once_then_degrades(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.calls = 0

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                self.calls += 1
                await asyncio.Future()
                yield b"\x00\x01"

        engine = Engine()
        socket = AsyncMock()
        result = await tts_node(
            self._state("thinking"),
            self._config(
                engine,
                socket,
                runtime_profile="golden",
                timeout_seconds=0.001,
            ),
        )

        assert engine.calls == 2
        socket.emit.assert_not_awaited()
        assert result["tts_audio"] is None
        assert result["media_status"].status == "degraded"
        assert result["media_status"].reason == "timeout"

    @pytest.mark.asyncio
    async def test_active_stream_uses_idle_timeout_instead_of_total_duration(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                for chunk in (b"\x00\x01", b"\x02\x03", b"\x04\x05", b"\x06\x07"):
                    await asyncio.sleep(0.02)
                    yield chunk

        socket = AsyncMock()
        result = await tts_node(
            self._state("thinking"),
            self._config(
                Engine(),
                socket,
                runtime_profile="golden",
                timeout_seconds=0.05,
            ),
        )

        assert result["media_status"].status == "ready"
        assert [call.args[0] for call in socket.emit.await_args_list] == [
            "chat:audio_stream_start",
            "chat:audio_stream_chunk",
            "chat:audio_stream_chunk",
            "chat:audio_stream_chunk",
            "chat:audio_stream_chunk",
            "chat:audio_stream_end",
        ]
        assert socket.emit.await_args_list[-1].args[1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_cancellation_after_first_chunk_emits_cancelled_end(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.waiting_after_chunk = asyncio.Event()

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                yield b"\x00\x01"
                self.waiting_after_chunk.set()
                await asyncio.Future()

        engine = Engine()
        socket = AsyncMock()
        task = asyncio.create_task(tts_node(self._state("sad"), self._config(engine, socket)))
        await engine.waiting_after_chunk.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert [call.args[0] for call in socket.emit.await_args_list] == [
            "chat:audio_stream_start",
            "chat:audio_stream_chunk",
            "chat:audio_stream_end",
        ]
        assert socket.emit.await_args_list[-1].args[1]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_user_interrupt_closes_stream_and_returns_without_waiting_for_provider(
        self,
    ) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.waiting_after_chunk = asyncio.Event()
                self.finalized = asyncio.Event()

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                try:
                    yield b"\x00\x01"
                    self.waiting_after_chunk.set()
                    await asyncio.Future()
                finally:
                    self.finalized.set()

        handler = get_interrupt_handler()
        handler.remove_session("socket-1")
        engine = Engine()
        socket = AsyncMock()
        try:
            task = asyncio.create_task(tts_node(self._state("sad"), self._config(engine, socket)))
            await asyncio.wait_for(engine.waiting_after_chunk.wait(), timeout=1.0)

            handler.set_interrupt("socket-1")
            result = await asyncio.wait_for(task, timeout=0.2)

            await asyncio.wait_for(engine.finalized.wait(), timeout=0.2)
            terminal = [
                call
                for call in socket.emit.await_args_list
                if call.args[0] == "chat:audio_stream_end"
            ]
            assert len(terminal) == 1
            assert terminal[0].args[1]["status"] == "cancelled"
            assert result["tts_audio"] is None
            assert result["media_status"].status == "skipped"
            assert result["media_status"].reason == "interrupted"
        finally:
            handler.remove_session("socket-1")

    @pytest.mark.asyncio
    async def test_user_interrupt_terminal_is_not_blocked_by_slow_provider_cleanup(
        self,
    ) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.waiting_after_chunk = asyncio.Event()
                self.cleanup_started = asyncio.Event()
                self.cleanup_release = asyncio.Event()
                self.finalized = asyncio.Event()

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                try:
                    yield b"\x00\x01"
                    self.waiting_after_chunk.set()
                    await asyncio.Future()
                finally:
                    self.cleanup_started.set()
                    await self.cleanup_release.wait()
                    self.finalized.set()

        handler = get_interrupt_handler()
        handler.remove_session("socket-1")
        engine = Engine()
        socket = AsyncMock()
        task = asyncio.create_task(tts_node(self._state("sad"), self._config(engine, socket)))
        try:
            await asyncio.wait_for(engine.waiting_after_chunk.wait(), timeout=1.0)
            handler.set_interrupt("socket-1")

            done, _ = await asyncio.wait({task}, timeout=0.5)

            assert task in done
            result = task.result()
            assert engine.cleanup_started.is_set()
            assert not engine.finalized.is_set()
            terminal = [
                call
                for call in socket.emit.await_args_list
                if call.args[0] == "chat:audio_stream_end"
            ]
            assert len(terminal) == 1
            assert terminal[0].args[1]["status"] == "cancelled"
            assert result["media_status"].reason == "interrupted"
        finally:
            engine.cleanup_release.set()
            if not task.done():
                await asyncio.wait_for(task, timeout=1.0)
            await asyncio.wait_for(engine.finalized.wait(), timeout=1.0)
            handler.remove_session("socket-1")

    @pytest.mark.asyncio
    async def test_start_emit_failure_closes_first_generator_before_retry(self) -> None:
        class Engine:
            supports_streaming = True
            supports_emotion_instructions = True
            sample_rate = 24000

            def __init__(self) -> None:
                self.calls = 0
                self.first_finalized = asyncio.Event()

            async def synthesize(self, *args, **kwargs):
                raise AssertionError("complete-audio fallback must not run")

            async def synthesize_stream(self, text: str, **kwargs):
                self.calls += 1
                call = self.calls
                if call == 2:
                    assert self.first_finalized.is_set()
                try:
                    yield b"\x00\x01"
                finally:
                    if call == 1:
                        self.first_finalized.set()

        engine = Engine()
        socket = AsyncMock()
        start_attempts = 0

        async def emit(event: str, payload: dict, **kwargs) -> None:
            nonlocal start_attempts
            if event == "chat:audio_stream_start":
                start_attempts += 1
                if start_attempts == 1:
                    raise RuntimeError("transient delivery failure")

        socket.emit.side_effect = emit

        result = await tts_node(self._state(), self._config(engine, socket))

        assert engine.calls == 2
        assert engine.first_finalized.is_set()
        assert result["media_status"].status == "ready"
        assert [call.args[0] for call in socket.emit.await_args_list] == [
            "chat:audio_stream_start",
            "chat:audio_stream_start",
            "chat:audio_stream_chunk",
            "chat:audio_stream_end",
        ]
