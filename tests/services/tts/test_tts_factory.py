"""Tests for TTS factory and mock implementation."""

from __future__ import annotations

import pytest

from animetta.services.tts.factory import TTSFactory
from animetta.services.tts.interface import TTSInterface
from animetta.services.tts.mock_tts import MockTTS


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


class TestTTSFactory:
    def test_create_mock(self):
        engine = TTSFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), TTSInterface)

    def test_create_unknown_returns_mock(self):
        engine = TTSFactory.create("nonexistent_provider")
        assert isinstance(engine, MockTTS)

    def test_create_mock_is_mock_tts(self):
        engine = TTSFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), MockTTS)


class TestMockTTS:
    @pytest.mark.asyncio
    async def test_synthesize_returns_string(self):
        tts = MockTTS()
        result = await tts.synthesize("Hello world")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_synthesize_with_output_path(self):
        tts = MockTTS()
        result = await tts.synthesize("Hello", output_path="/tmp/test.wav")
        assert result == "/tmp/test.wav"

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        tts = MockTTS()
        await tts.close()

    def test_from_config(self):
        tts = MockTTS.from_config(None)
        assert isinstance(tts, MockTTS)

    def test_metadata_defaults(self):
        tts = MockTTS()
        assert tts.audio_format == "wav"
        assert tts.sample_rate == 24000
        assert tts.requires_gpu is False
