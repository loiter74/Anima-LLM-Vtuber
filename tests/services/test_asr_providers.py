from __future__ import annotations

from animetta.config.providers.asr import (
    FasterWhisperASRConfig,
    FunASRConfig,
    GLMASRConfig,
    MockASRConfig,
)
from animetta.services.asr import GLMASR, ASRFactory, ASRInterface, FasterWhisperASR, FunASRASR

"""
Tests for ASR provider implementations.

Covers:
- ASRInterface contract (transcribe, close)
- MockASR: transcribe returns text, close()
- FasterWhisperASR: from_config, transcribe audio bytes, close()
- GLMASR: from_config, transcribe, close()
- FunASRASR: from_config takes dict
- ASRFactory.create with provider + kwargs, fallback to MockASR on error
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from animetta.services.asr import MockASR

# ── Module-level sys.modules injection ──────────────────────────────
# External packages imported INSIDE methods (lazy imports). We inject
# mocks before any anima imports so those method bodies never fail.
sys.modules["faster_whisper"] = MagicMock()
sys.modules["zai"] = MagicMock()
sys.modules["funasr"] = MagicMock()



# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def audio_bytes() -> bytes:
    """16-bit PCM audio, 8000 samples (~0.5 s at 16 kHz)."""
    return b"\x01\x00" * 8000


# ── Interface Implementation Tests ──────────────────────────────────


class TestASRInterface:
    """Verify all ASR providers implement ASRInterface correctly."""

    PROVIDER_CLASSES = [MockASR, GLMASR, FunASRASR, FasterWhisperASR]

    @staticmethod
    def _get_abstract_methods() -> set:
        abstract = set()
        for attr_name in dir(ASRInterface):
            attr = getattr(ASRInterface, attr_name, None)
            if getattr(attr, "__isabstractmethod__", False):
                abstract.add(attr_name)
        return abstract

    def test_all_providers_inherit_interface(self):
        """Each provider class must be a concrete subclass of ASRInterface."""
        for cls in self.PROVIDER_CLASSES:
            assert issubclass(cls, ASRInterface), (
                f"{cls.__name__} does not inherit ASRInterface"
            )

    def test_all_abstract_methods_implemented(self):
        """Each provider must implement every abstract method (not leave it abstract)."""
        abstract_methods = self._get_abstract_methods()
        for cls in self.PROVIDER_CLASSES:
            for method in abstract_methods:
                impl = getattr(cls, method, None)
                assert impl is not None, f"{cls.__name__} is missing '{method}'"
                assert not getattr(impl, "__isabstractmethod__", False), (
                    f"{cls.__name__} has not implemented '{method}'"
                )


# ── MockASR Tests ───────────────────────────────────────────────────


class TestMockASR:
    """Tests for the MockASR provider."""

    def test_constructor_defaults(self):
        """Default constructor should pick a random TEST_PHRASE."""
        asr = MockASR()
        assert asr.mock_response in MockASR.TEST_PHRASES

    def test_constructor_custom_response(self):
        """Constructor should accept a custom mock_response."""
        asr = MockASR(mock_response="custom response")
        assert asr.mock_response == "custom response"

    def test_from_config_returns_instance(self):
        """from_config should return a MockASR instance."""
        instance = MockASR.from_config(MagicMock())
        assert isinstance(instance, MockASR)

    @pytest.mark.asyncio
    async def test_transcribe_returns_string(self, audio_bytes):
        """transcribe() should return a non-empty string."""
        asr = MockASR(mock_response="test result")
        result = await asr.transcribe(audio_bytes)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_transcribe_accepts_bytes(self):
        """transcribe() should accept raw bytes."""
        asr = MockASR()
        result = await asr.transcribe(b"\x01\x00" * 1600)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_transcribe_accepts_string_path(self):
        """transcribe() should accept a string file path."""
        asr = MockASR()
        result = await asr.transcribe("/fake/path/audio.wav")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_transcribe_accepts_path_object(self):
        """transcribe() should accept a Path object."""
        asr = MockASR()
        result = await asr.transcribe(Path("/fake/path/audio.wav"))
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should not raise."""
        asr = MockASR()
        await asr.close()


# ── FasterWhisperASR Tests ──────────────────────────────────────────


class TestFasterWhisperASR:
    """Tests for the FasterWhisperASR provider (model loading mocked)."""

    def test_constructor_defaults(self):
        """Constructor should apply sensible defaults."""
        asr = FasterWhisperASR()
        assert asr.model_name == "distil-large-v3"
        assert asr.language == "zh"
        assert asr.device == "auto"
        assert asr.compute_type == "default"
        assert asr.beam_size == 5
        assert asr.vad_filter is True

    def test_from_config_returns_instance(self):
        """from_config with a mock config object."""
        config = MagicMock()
        config.model = "base"
        config.language = "en"
        config.device = "cpu"
        config.compute_type = "int8"
        config.download_root = None
        config.beam_size = 3
        config.vad_filter = False
        config.vad_parameters = {}

        instance = FasterWhisperASR.from_config(config)
        assert isinstance(instance, FasterWhisperASR)
        assert instance.model_name == "base"
        assert instance.language == "en"
        assert instance.device == "cpu"
        assert instance.compute_type == "int8"
        assert instance.beam_size == 3
        assert instance.vad_filter is False

    def test_get_model_loads_lazily(self):
        """_get_model() should lazily instantiate WhisperModel."""
        mock_model = MagicMock()
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperASR(model="base", device="cpu")
            assert asr._model is None
            model = asr._get_model()
        assert model is mock_model
        assert asr._model is mock_model
        assert asr._get_model() is mock_model

    def test_get_model_caches(self):
        """_get_model() should only construct WhisperModel once."""
        mock_model = MagicMock()
        with patch("faster_whisper.WhisperModel", return_value=mock_model) as mock_ctr:
            asr = FasterWhisperASR(model="base", device="cpu")
            asr._get_model()
            asr._get_model()
        mock_ctr.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_returns_string(self, audio_bytes):
        """transcribe() should return transcribed text."""
        asr = FasterWhisperASR(model="base", device="cpu")

        mock_model = MagicMock()
        segment = MagicMock()
        segment.text = "hello world"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95
        mock_model.transcribe.return_value = ([segment], mock_info)
        asr._model = mock_model

        result = await asr.transcribe(audio_bytes)
        assert isinstance(result, str)
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self, audio_bytes):
        """transcribe() should handle empty transcription gracefully."""
        asr = FasterWhisperASR(model="base", device="cpu")

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.0
        mock_model.transcribe.return_value = ([], mock_info)
        asr._model = mock_model

        result = await asr.transcribe(audio_bytes)
        assert result == ""

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should set _model to None."""
        asr = FasterWhisperASR(model="base", device="cpu")
        asr._model = MagicMock()
        await asr.close()
        assert asr._model is None

    @pytest.mark.asyncio
    async def test_preload(self):
        """preload() should trigger model loading."""
        mock_model = MagicMock()
        with patch("faster_whisper.WhisperModel", return_value=mock_model):
            asr = FasterWhisperASR(model="base", device="cpu")
            await asr.preload()
        assert asr._model is not None

    @pytest.mark.asyncio
    async def test_preload_idempotent(self):
        """preload() should be idempotent (safe to call multiple times)."""
        mock_model = MagicMock()
        with patch("faster_whisper.WhisperModel", return_value=mock_model) as mock_ctr:
            asr = FasterWhisperASR(model="base", device="cpu")
            await asr.preload()
            await asr.preload()
        mock_ctr.assert_called_once()


# ── GLMASR Tests ────────────────────────────────────────────────────


class TestGLMASR:
    """Tests for the GLM ASR provider (zai module sys.modules-mocked at file top)."""

    def test_constructor_stores_params(self):
        """Constructor should store api_key, model, stream."""
        asr = GLMASR(api_key="test-key", model="glm-asr", stream=False)
        assert asr.api_key == "test-key"
        assert asr.model == "glm-asr"
        assert asr.stream is False

    def test_from_config_returns_instance(self):
        """from_config with a mock config object."""
        config = MagicMock()
        config.api_key = "test-glm-key"
        config.model = "glm-asr-2512"
        config.stream = False

        instance = GLMASR.from_config(config)
        assert isinstance(instance, GLMASR)
        assert instance.api_key == "test-glm-key"
        assert instance.model == "glm-asr-2512"
        assert instance.stream is False

    def test_get_client_lazy_loads(self):
        """_get_client() should lazily create ZhipuAiClient."""
        with patch("zai.ZhipuAiClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            asr = GLMASR(api_key="test-key")
            assert asr._client is None
            client = asr._get_client()
        assert client is mock_client
        assert asr._client is mock_client
        assert asr._get_client() is mock_client
        mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_returns_string(self, audio_bytes):
        """transcribe() should return transcribed text."""
        asr = GLMASR(api_key="test-key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "GLM ASR response"
        mock_client.audio.transcriptions.create.return_value = mock_response
        asr._client = mock_client

        result = await asr.transcribe(audio_bytes)
        assert result == "GLM ASR response"

    @pytest.mark.asyncio
    async def test_transcribe_calls_create_with_audio(self, audio_bytes):
        """transcribe() should call client.audio.transcriptions.create with audio bytes."""
        asr = GLMASR(api_key="test-key")
        mock_client = MagicMock()
        asr._client = mock_client

        await asr.transcribe(audio_bytes)

        assert mock_client.audio.transcriptions.create.called
        call_args = mock_client.audio.transcriptions.create.call_args[1]
        assert "file" in call_args

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should set _client to None."""
        asr = GLMASR(api_key="test-key")
        asr._client = MagicMock()
        await asr.close()
        assert asr._client is None


# ── FunASRASR Tests ─────────────────────────────────────────────────


class TestFunASRASR:
    """Tests for the FunASR ASR provider (funasr module sys.modules-mocked at file top)."""

    def test_constructor_defaults(self):
        """Constructor should apply sensible defaults."""
        asr = FunASRASR()
        assert asr.model_name == "paraformer-zh"
        assert asr.device == "cuda"
        assert asr.ncpu == 4

    def test_from_config_takes_dict(self):
        """from_config should accept a plain dict (FunASRASR uses .get() internally)."""
        config_dict: dict = {
            "type": "funasr",
            "model": "paraformer-zh",
            "language": "zh",
            "device": "cpu",
            "ncpu": 2,
            "vad_model": None,
            "punc_model": None,
        }
        instance = FunASRASR.from_config(config_dict)
        assert isinstance(instance, FunASRASR)
        assert instance.model_name == "paraformer-zh"
        assert instance.device == "cpu"
        assert instance.ncpu == 2
        assert instance.vad_model is None
        assert instance.punc_model is None

    def test_from_config_dict_partial(self):
        """from_config with partial dict should fall back to defaults."""
        instance = FunASRASR.from_config({"type": "funasr"})
        assert isinstance(instance, FunASRASR)
        assert instance.model_name == "paraformer-zh"
        assert instance.device == "cuda"
        assert instance.ncpu == 4

    def test_get_model_loads_lazily(self):
        """_get_model() should lazily instantiate the FunASR AutoModel."""
        mock_model = MagicMock()
        with patch("funasr.AutoModel", return_value=mock_model):
            asr = FunASRASR(model="paraformer-zh", device="cpu")
            assert asr._model is None
            model = asr._get_model()
        assert model is mock_model
        assert asr._model is mock_model
        assert asr._get_model() is mock_model

    def test_get_model_caches(self):
        """_get_model() should only construct AutoModel once."""
        mock_model = MagicMock()
        with patch("funasr.AutoModel", return_value=mock_model) as mock_ctr:
            asr = FunASRASR(model="paraformer-zh", device="cpu")
            asr._get_model()
            asr._get_model()
        mock_ctr.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_returns_string(self, audio_bytes):
        """transcribe() should return transcribed text."""
        asr = FunASRASR(model="paraformer-zh", device="cpu")
        mock_model = MagicMock()
        mock_model.generate.return_value = [{"text": "FunASR result"}]
        asr._model = mock_model

        result = await asr.transcribe(audio_bytes)
        assert result == "FunASR result"

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self, audio_bytes):
        """transcribe() should handle empty transcription."""
        asr = FunASRASR(model="paraformer-zh", device="cpu")
        mock_model = MagicMock()
        mock_model.generate.return_value = []
        asr._model = mock_model

        result = await asr.transcribe(audio_bytes)
        assert result == ""

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should release model reference."""
        asr = FunASRASR(model="paraformer-zh", device="cpu")
        asr._model = MagicMock()
        await asr.close()
        assert asr._model is None


# ── ASRFactory Tests ────────────────────────────────────────────────


class TestASRFactory:
    """Tests for the ASRFactory."""

    @staticmethod
    def _target(service):
        """Return the concrete provider behind the observability proxy."""
        return getattr(service, "_target", service)

    def test_create_unknown_provider_falls_back(self):
        """create() with unknown provider should fall back to MockASR."""
        result = ASRFactory.create("unknown_provider")
        assert isinstance(self._target(result), MockASR)

    def test_create_with_kwargs_unknown(self):
        """create() with kwargs for unknown provider falls back to MockASR."""
        result = ASRFactory.create("nonexistent", model="test", language="en")
        assert isinstance(self._target(result), MockASR)

    @patch("animetta.services.asr.factory.ASRFactory._build_config")
    @patch("animetta.services.asr.factory.ProviderRegistry.create_service")
    def test_create_calls_registry(self, mock_create_service, mock_build_config):
        """create() should build config and delegate to ProviderRegistry."""
        mock_config = MagicMock()
        mock_config.type = "faster_whisper"
        mock_build_config.return_value = mock_config
        mock_asr = MagicMock()
        mock_create_service.return_value = mock_asr

        result = ASRFactory.create("faster_whisper", model="base", device="cpu")

        mock_build_config.assert_called_once_with(
            "faster_whisper", {"model": "base", "device": "cpu"}
        )
        mock_create_service.assert_called_once_with("asr", mock_config)
        assert result is not None

    @patch("animetta.services.asr.factory.ProviderRegistry.create_service")
    def test_create_fallback_on_exception(self, mock_create_service):
        """create() should fall back to MockASR when ProviderRegistry raises."""
        mock_create_service.side_effect = ValueError("Service creation failed")
        result = ASRFactory.create("faster_whisper")
        assert isinstance(self._target(result), MockASR)

    @patch("animetta.services.asr.factory.logger")
    def test_create_unknown_logs_warning(self, mock_logger):
        """create() with unknown provider should log a warning."""
        ASRFactory.create("bogus_provider")
        mock_logger.warning.assert_called()

    def test_build_config_faster_whisper(self):
        """_build_config should build a FasterWhisperASRConfig."""

        config = ASRFactory._build_config(
            "faster_whisper", {"model": "base", "device": "cpu", "language": "en"}
        )
        assert isinstance(config, FasterWhisperASRConfig)
        assert config.model == "base"
        assert config.device == "cpu"
        assert config.language == "en"

    def test_build_config_glm(self):
        """_build_config should build a GLMASRConfig."""

        config = ASRFactory._build_config("glm", {"api_key": "test-key"})
        assert isinstance(config, GLMASRConfig)
        assert config.api_key == "test-key"

    def test_build_config_funasr(self):
        """_build_config should build a FunASRConfig."""

        config = ASRFactory._build_config(
            "funasr", {"model": "paraformer-zh", "device": "cpu"}
        )
        assert isinstance(config, FunASRConfig)
        assert config.model == "paraformer-zh"

    def test_build_config_mock(self):
        """_build_config should build a MockASRConfig."""

        config = ASRFactory._build_config("mock", {})
        assert isinstance(config, MockASRConfig)

    def test_build_config_unknown_returns_none(self):
        """_build_config should return None for an unknown provider."""
        config = ASRFactory._build_config("nonexistent", {})
        assert config is None

    def test_get_available_configs(self):
        """get_available_configs should return a list of provider names."""
        providers = ASRFactory.get_available_configs()
        assert isinstance(providers, list)
