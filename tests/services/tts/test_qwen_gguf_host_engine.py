from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from animetta_qwen_tts.gguf_host import GGUFHostEngine, build_host_service_from_env


class FakeStream:
    def __init__(self) -> None:
        self.callback: Any = None
        self.voice_args: tuple[Any, ...] | None = None
        self.clone_calls: list[dict[str, Any]] = []

    def set_voice(self, path: str, text: str) -> bool:
        self.voice_args = (path, text)
        return True

    def set_audio_chunk_callback(self, callback: Any) -> None:
        self.callback = callback

    def clone(self, **kwargs: Any) -> Any:
        self.clone_calls.append(kwargs)
        chunks = [
            np.array([-1.0, -0.5, 0.5, 1.0], dtype=np.float32),
            np.array([0.25, -0.25], dtype=np.float32),
        ]
        if self.callback is not None:
            for chunk in chunks:
                self.callback(chunk)
        return SimpleNamespace(audio=np.concatenate(chunks))


class FakeRuntimeEngine:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.stream = FakeStream()
        self.closed = False

    def create_stream(self) -> FakeStream:
        return self.stream

    def shutdown(self) -> None:
        self.closed = True


def host_engine(tmp_path: Path) -> GGUFHostEngine:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    return GGUFHostEngine(
        model_dir=tmp_path / "model",
        reference_audio=reference,
        reference_text="秉持优雅。",
        engine_factory=FakeRuntimeEngine,
        config_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )


async def test_preload_loads_runtime_and_reference_voice(tmp_path: Path) -> None:
    engine = host_engine(tmp_path)

    await engine.preload()

    assert engine._engine is not None
    assert engine._engine.kwargs == {
        "model_dir": str(tmp_path / "model"),
        "onnx_provider": "DML",
        "verbose": False,
    }
    assert engine._stream.voice_args == (
        str(tmp_path / "reference.wav"),
        "秉持优雅。",
    )


async def test_preload_rejects_runtime_that_did_not_become_ready(
    tmp_path: Path,
) -> None:
    class FailedRuntimeEngine(FakeRuntimeEngine):
        def __bool__(self) -> bool:
            return False

    engine = host_engine(tmp_path)
    engine._engine_factory = FailedRuntimeEngine

    with pytest.raises(RuntimeError, match="did not become ready"):
        await engine.preload()


async def test_stream_yields_callback_pcm16_chunks_in_order(tmp_path: Path) -> None:
    engine = host_engine(tmp_path)
    await engine.preload()

    chunks = [
        chunk
        async for chunk in engine.synthesize_stream(
            "你好",
            language="Chinese",
            max_new_tokens=48,
        )
    ]

    assert chunks == [
        b"\x01\x80\x01\xc0\xff?\xff\x7f",
        b"\xff\x1f\x01\xe0",
    ]
    assert engine._stream.clone_calls[0]["text"] == "你好"
    assert engine._stream.clone_calls[0]["language"] == "Chinese"
    assert engine._stream.clone_calls[0]["config"].streaming is True


async def test_non_streaming_returns_complete_24khz_mono_wav(tmp_path: Path) -> None:
    engine = host_engine(tmp_path)
    await engine.preload()

    audio = await engine.synthesize("完整语音", language="Chinese")

    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes())


async def test_close_is_idempotent(tmp_path: Path) -> None:
    engine = host_engine(tmp_path)
    await engine.preload()
    runtime = engine._engine

    await engine.close()
    await engine.close()

    assert runtime.closed is True


def test_host_service_environment_publishes_fixed_identity(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference")
    monkeypatch.setenv("QWEN_TTS_API_KEY", "host-secret")
    monkeypatch.setenv("QWEN_HOST_TTS_MODEL_DIR", str(tmp_path / "model"))
    monkeypatch.setenv("QWEN_HOST_TTS_REFERENCE_AUDIO", str(reference))
    monkeypatch.setenv("QWEN_HOST_TTS_REFERENCE_TEXT", "秉持优雅。")
    monkeypatch.setenv(
        "QWEN_HOST_TTS_REFERENCE_SHA256",
        hashlib.sha256(b"reference").hexdigest(),
    )

    service = build_host_service_from_env(engine_factory=FakeRuntimeEngine)

    assert service.settings.provider == "qwen3-tts-gguf-host"
    assert service.settings.model == "Qwen3-TTS-1.7B-Base"
    assert service.settings.voice == "vivian-synthetic-zh"
    assert service.settings.quantization == ("talker=Q5_K,predictor=Q8_0,onnx=FP16")
    assert service.settings.runtime_commit == ("0eb32e283ee46b86820c67843abb04cf12bc58d7")
    assert service.settings.sample_rate == 24000


def test_host_service_defaults_to_bundled_synthetic_reference(monkeypatch: Any) -> None:
    monkeypatch.setenv("QWEN_TTS_API_KEY", "host-secret")
    for name in (
        "QWEN_HOST_TTS_REFERENCE_AUDIO",
        "QWEN_HOST_TTS_REFERENCE_TEXT",
        "QWEN_HOST_TTS_REFERENCE_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)

    service = build_host_service_from_env(engine_factory=FakeRuntimeEngine)

    assert isinstance(service.engine, GGUFHostEngine)
    assert service.engine.reference_audio.name == "animetta-vivian-reference.wav"
    assert service.engine.reference_text == "你好，我是千问，你今天过得好吗？"
    assert hashlib.sha256(service.engine.reference_audio.read_bytes()).hexdigest().upper() == (
        "A2BBFF2BB0E33C72027DC0BB24565FA288BDF81FD147172861A3BC8831412E73"
    )
