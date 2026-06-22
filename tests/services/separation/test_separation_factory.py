"""Tests for Separation factory and mock implementation."""

from __future__ import annotations

import pytest

from animetta.services.separation.factory import SeparationFactory
from animetta.services.separation.interface import SeparationInterface
from animetta.services.separation.mock_separation import MockSeparation


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


class TestSeparationFactory:
    def test_create_mock(self):
        engine = SeparationFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), SeparationInterface)

    def test_create_unknown_returns_mock(self):
        engine = SeparationFactory.create("nonexistent_provider")
        assert isinstance(unwrap_tracing_proxy(engine), MockSeparation)

    def test_create_mock_is_mock_separation(self):
        engine = SeparationFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), MockSeparation)


class TestMockSeparation:
    @pytest.mark.asyncio
    async def test_separate_returns_stems(self):
        sep = MockSeparation()
        audio = b"\x00\x01\x02\x03"
        result = await sep.separate(audio)
        assert isinstance(result, dict)
        assert "vocals" in result
        assert "other" in result
        assert result["vocals"] == audio

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        sep = MockSeparation()
        await sep.close()

    def test_from_config(self):
        sep = MockSeparation.from_config(None)
        assert isinstance(sep, MockSeparation)
