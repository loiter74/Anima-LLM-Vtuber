"""Tests for ASR factory and mock implementation."""

from __future__ import annotations

import pytest

from animetta.services.asr.factory import ASRFactory
from animetta.services.asr.interface import ASRInterface
from animetta.services.asr.mock_asr import MockASR


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


class TestASRFactory:
    def test_create_mock(self):
        engine = ASRFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), ASRInterface)

    def test_create_unknown_returns_mock(self):
        engine = ASRFactory.create("nonexistent_provider")
        assert isinstance(unwrap_tracing_proxy(engine), MockASR)

    def test_create_mock_is_mock_asr(self):
        engine = ASRFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), MockASR)


class TestMockASR:
    @pytest.mark.asyncio
    async def test_transcribe_returns_string(self):
        asr = MockASR()
        result = await asr.transcribe(b"\x00" * 1000)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        asr = MockASR()
        await asr.close()

    def test_from_config(self):
        asr = MockASR.from_config(None)
        assert isinstance(asr, MockASR)

    def test_custom_mock_response(self):
        asr = MockASR(mock_response="test phrase")
        assert asr.mock_response == "test phrase"
