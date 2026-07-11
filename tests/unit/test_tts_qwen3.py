from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts.qwen3 import Qwen3TTSConfig
from animetta.services.tts.qwen3_tts import Qwen3TTSTTS

"""Unit tests for Qwen3-TTS provider (config + registry + from_config)"""

import pytest


def _write_valid_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24_000)
        wav_file.writeframes(b"\x00\x00" * 32)


class _LoadSpyQwen(Qwen3TTSTTS):
    def __init__(self, **kwargs):
        super().__init__(device="cpu", **kwargs)
        self.load_calls = 0

    def _load_model(self):
        self.load_calls += 1
        self._model = SimpleNamespace(create_voice_clone_prompt=lambda **_kwargs: [object()])
        self._loaded = True


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
        assert Qwen3TTSConfig(max_new_tokens=32).max_new_tokens == 32
        with pytest.raises(Exception):
            Qwen3TTSConfig(max_new_tokens=31)

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

    @pytest.mark.parametrize("payload", [b"", b"not-a-wave-file"])
    async def test_preload_rejects_invalid_reference_before_model_load(
        self,
        tmp_path: Path,
        payload: bytes,
    ):
        reference = tmp_path / "alice.wav"
        reference.write_bytes(payload)
        tts = _LoadSpyQwen(
            ref_audio_path=str(reference),
            ref_text="Alice reference transcript",
            x_vector_only=False,
        )

        with pytest.raises(ValueError, match="WAV"):
            await tts.preload()

        assert tts.load_calls == 0
        assert tts.preload_status == {
            "state": "failed",
            "ready": False,
            "error": "ValueError",
        }
        await tts.close()

    async def test_preload_rejects_missing_reference_before_model_load(self, tmp_path: Path):
        tts = _LoadSpyQwen(
            ref_audio_path=str(tmp_path / "missing.wav"),
            ref_text="Alice reference transcript",
            x_vector_only=False,
        )

        with pytest.raises(FileNotFoundError, match="Reference audio"):
            await tts.preload()

        assert tts.load_calls == 0
        await tts.close()

    async def test_preload_requires_transcript_for_icl_mode(self, tmp_path: Path):
        reference = tmp_path / "alice.wav"
        _write_valid_wav(reference)
        tts = _LoadSpyQwen(
            ref_audio_path=str(reference),
            ref_text="  ",
            x_vector_only=False,
        )

        with pytest.raises(ValueError, match="ref_text"):
            await tts.preload()

        assert tts.load_calls == 0
        await tts.close()

    def test_preload_status_is_content_free_before_loading(self):
        tts = Qwen3TTSTTS(
            device="cpu",
            ref_audio_path="C:/private/alice.wav",
            ref_text="private transcript",
            x_vector_only=False,
        )

        assert tts.preload_status == {
            "state": "pending",
            "ready": False,
            "error": None,
        }
        assert "private" not in repr(tts.preload_status)

    def test_cuda_optimization_sets_legal_cudnn_benchmark_flag(self):
        torch_module = SimpleNamespace(
            backends=SimpleNamespace(
                cudnn=SimpleNamespace(benchmark=False),
                cuda=SimpleNamespace(
                    matmul=SimpleNamespace(allow_tf32=False),
                    enable_flash_sdp=lambda _enabled: None,
                    enable_mem_efficient_sdp=lambda _enabled: None,
                ),
            )
        )
        tts = Qwen3TTSTTS(device="cuda:0")

        tts._enable_cuda_optimizations(torch_module)

        assert torch_module.backends.cudnn.benchmark is True
        assert not hasattr(torch_module.backends.cudnn.benchmark, "main")
        assert torch_module.backends.cuda.matmul.allow_tf32 is True
