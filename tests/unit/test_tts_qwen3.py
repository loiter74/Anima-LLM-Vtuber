from __future__ import annotations

from animetta.core.config.core.registry import ProviderRegistry
from animetta.core.config.providers.tts.qwen3 import Qwen3TTSConfig
from animetta.services.tts.qwen3_tts import Qwen3TTSTTS

"""Unit tests for Qwen3-TTS provider (config + registry + from_config)"""

import pytest


class TestQwen3TTSConfigUnit:
    def test_default_config_values(self):
        config = Qwen3TTSConfig()
        assert config.type == "qwen3"
        assert config.model == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
        assert config.speaker == "Vivian"
        assert config.device == "cuda:0"
        assert config.default_instruct == ""
        assert config.language == "Chinese"

    def test_custom_config_values(self):
        config = Qwen3TTSConfig(
            model="custom/model",
            speaker="Aria",
            device="cpu",
            default_instruct="用愤怒的语气说",
            language="English",
        )
        assert config.speaker == "Aria"
        assert config.device == "cpu"
        assert config.default_instruct == "用愤怒的语气说"

    def test_config_registered_in_registry(self):
        assert "qwen3" in ProviderRegistry.list_services("tts")

    def test_max_new_tokens_bounds(self):
        with pytest.raises(Exception):
            Qwen3TTSConfig(max_new_tokens=100)

    @pytest.mark.parametrize("dtype", ["bfloat16", "float16"])
    def test_valid_dtype_values(self, dtype):
        config = Qwen3TTSConfig(dtype=dtype)
        assert config.dtype == dtype

    def test_voice_clone_fields_default_to_none(self):
        config = Qwen3TTSConfig()
        assert config.ref_audio_path is None
        assert config.ref_text is None
        assert config.x_vector_only is True

    def test_voice_clone_fields_custom_values(self):
        config = Qwen3TTSConfig(
            ref_audio_path="E:/test/audio.wav",
            ref_text="こんにちは",
            x_vector_only=False,
        )
        assert config.ref_audio_path == "E:/test/audio.wav"
        assert config.ref_text == "こんにちは"
        assert config.x_vector_only is False


class TestQwen3TTSTTSUnit:
    def test_from_config_creates_lazy(self):
        config = Qwen3TTSConfig(device="cpu")
        tts = Qwen3TTSTTS.from_config(config)
        assert tts._model is None
        assert tts._loaded is False

    def test_from_config_preserves_instruct(self):
        config = Qwen3TTSConfig(
            default_instruct="温柔地轻声说",
            speaker="Luna",
        )
        tts = Qwen3TTSTTS.from_config(config)
        assert tts.default_instruct == "温柔地轻声说"
        assert tts.speaker == "Luna"

    def test_server_switching_preserves_preload_method(self):
        tts = Qwen3TTSTTS(device="cpu")
        assert hasattr(tts, "preload") and callable(tts.preload)
        assert hasattr(tts, "close") and callable(tts.close)

    def test_lock_initialized(self):
        tts = Qwen3TTSTTS(device="cpu")
        assert hasattr(tts, "_load_lock")
        assert hasattr(tts, "_synth_done")

    def test_from_config_preserves_voice_clone_params(self):
        config = Qwen3TTSConfig(
            device="cpu",
            ref_audio_path="test/ref.wav",
            ref_text="hello",
            x_vector_only=False,
        )
        tts = Qwen3TTSTTS.from_config(config)
        assert tts.ref_audio_path == "test/ref.wav"
        assert tts.ref_text == "hello"
        assert tts.x_vector_only is False

    def test_voice_clone_prompt_cache_initialized(self):
        tts = Qwen3TTSTTS(device="cpu", ref_audio_path="test.wav")
        assert tts._voice_clone_prompt is None
