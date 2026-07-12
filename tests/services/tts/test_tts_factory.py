"""Tests for TTS factory and mock implementation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from animetta.services.tts.factory import TTSFactory
from animetta.services.tts.interface import TTSInterface
from animetta.services.tts.mock_tts import MockTTS
from animetta.tracing.proxy import TracingProxy


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


class TestTTSFactory:
    def test_create_mock(self):
        engine = TTSFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), TTSInterface)

    def test_create_unknown_returns_mock(self):
        engine = TTSFactory.create("nonexistent_provider")
        assert isinstance(unwrap_tracing_proxy(engine), MockTTS)

    def test_create_mock_is_mock_tts(self):
        engine = TTSFactory.create("mock")
        assert isinstance(unwrap_tracing_proxy(engine), MockTTS)

    def test_strict_registry_error_is_propagated_without_mock_fallback(self):
        provider_error = RuntimeError("provider initialization failed")

        with (
            patch(
                "animetta.services.tts.factory.ProviderRegistry.create_service",
                side_effect=provider_error,
            ),
            patch("animetta.services.tts.factory.MockTTS") as mock_tts,
            pytest.raises(RuntimeError) as exc_info,
        ):
            TTSFactory.create("edge_tts", strict=True)

        assert exc_info.value is provider_error
        mock_tts.assert_not_called()

    @pytest.mark.parametrize(
        "registry_result",
        [
            MockTTS(),
            TracingProxy(MockTTS(), service_name="tts"),
            TracingProxy(
                TracingProxy(MockTTS(), service_name="tts"),
                service_name="tts",
            ),
        ],
        ids=["bare", "single-proxy", "nested-proxy"],
    )
    def test_strict_non_mock_provider_rejects_registry_mock(self, registry_result):
        """A registry bug cannot smuggle MockTTS through strict creation."""
        with (
            patch(
                "animetta.services.tts.factory.ProviderRegistry.create_service",
                return_value=registry_result,
            ),
            pytest.raises(
                RuntimeError,
                match="Strict TTS provider creation returned MockTTS",
            ),
        ):
            TTSFactory.create("edge_tts", strict=True)

    def test_unknown_provider_raises_in_strict_mode(self):
        with (
            patch("animetta.services.tts.factory.MockTTS") as mock_tts,
            pytest.raises(ValueError, match="Unknown TTS provider"),
        ):
            TTSFactory.create("nonexistent_provider", strict=True)

        mock_tts.assert_not_called()

    def test_explicit_mock_provider_is_allowed_in_strict_factory_mode(self):
        engine = TTSFactory.create("mock", strict=True)

        assert isinstance(unwrap_tracing_proxy(engine), MockTTS)

    def test_non_strict_registry_error_keeps_mock_fallback(self):
        with patch(
            "animetta.services.tts.factory.ProviderRegistry.create_service",
            side_effect=RuntimeError("provider initialization failed"),
        ):
            engine = TTSFactory.create("edge_tts")

        assert isinstance(unwrap_tracing_proxy(engine), MockTTS)


class TestMockTTS:
    @pytest.mark.asyncio
    async def test_synthesize_returns_wav_bytes(self):
        tts = MockTTS()
        result = await tts.synthesize("Hello world")
        assert isinstance(result, bytes)
        assert result.startswith(b"RIFF")

    @pytest.mark.asyncio
    async def test_synthesize_with_output_path(self, tmp_path):
        tts = MockTTS()
        output_path = tmp_path / "test.wav"
        result = await tts.synthesize("Hello", output_path=output_path)
        assert result == str(output_path)
        assert output_path.read_bytes().startswith(b"RIFF")

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
