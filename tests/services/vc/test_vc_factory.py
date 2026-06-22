"""Tests for VC factory and mock implementation."""

from __future__ import annotations

import pytest

from animetta.services.vc.factory import VCFactory
from animetta.services.vc.interface import VCInterface
from animetta.services.vc.mock_vc import MockVC


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


class TestVCFactory:
    def test_create_mock(self):
        engine = VCFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), VCInterface)

    def test_create_unknown_returns_mock(self):
        engine = VCFactory.create("nonexistent_provider")
        assert isinstance(engine, MockVC)

    def test_create_mock_is_mock_vc(self):
        engine = VCFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), MockVC)


class TestMockVC:
    @pytest.mark.asyncio
    async def test_convert_passthrough(self):
        vc = MockVC()
        audio = b"\x00\x01\x02\x03"
        result = await vc.convert(audio)
        assert result == audio

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        vc = MockVC()
        await vc.close()

    def test_from_config(self):
        vc = MockVC.from_config(None)
        assert isinstance(vc, MockVC)
