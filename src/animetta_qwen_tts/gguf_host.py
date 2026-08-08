"""Windows-host adapter for the local Qwen3-TTS GGUF runtime."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import threading
import wave
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import numpy as np

_STREAM_END = object()
_RUNTIME_COMMIT = "0eb32e283ee46b86820c67843abb04cf12bc58d7"
_REFERENCE_AUDIO = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "personas"
    / "voices"
    / "animetta-vivian-reference.wav"
)
_REFERENCE_SHA256 = "A2BBFF2BB0E33C72027DC0BB24565FA288BDF81FD147172861A3BC8831412E73"
_REFERENCE_TEXT = "你好，我是千问，你今天过得好吗？"
_VOICE = "vivian-synthetic-zh"


class GGUFHostEngine:
    """Expose the synchronous GGUF runtime through the worker engine contract."""

    def __init__(
        self,
        *,
        model_dir: Path,
        reference_audio: Path,
        reference_text: str,
        onnx_provider: str = "DML",
        sample_rate: int = 24000,
        engine_factory: Callable[..., Any] | None = None,
        config_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.reference_audio = reference_audio
        self.reference_text = reference_text
        self.onnx_provider = onnx_provider
        self.sample_rate = sample_rate
        self._engine_factory = engine_factory
        self._config_factory = config_factory
        self._engine: Any = None
        self._stream: Any = None
        self._closed = False

    async def preload(self) -> None:
        if self._engine is not None:
            return
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        engine_factory = self._engine_factory
        if engine_factory is None:
            from qwen3_tts_gguf.inference import TTSEngine

            engine_factory = TTSEngine
        engine = engine_factory(
            model_dir=str(self.model_dir),
            onnx_provider=self.onnx_provider,
            verbose=False,
        )
        if not engine:
            engine.shutdown()
            raise RuntimeError("Qwen GGUF runtime did not become ready")
        stream = engine.create_stream()
        if stream is None:
            engine.shutdown()
            raise RuntimeError("Qwen GGUF runtime could not create a stream")
        voice = stream.set_voice(
            str(self.reference_audio),
            self.reference_text,
        )
        if not voice:
            engine.shutdown()
            raise RuntimeError("Qwen GGUF reference voice initialization failed")
        self._engine = engine
        self._stream = stream

    def _config(self, *, streaming: bool, max_new_tokens: int) -> Any:
        config_factory = self._config_factory
        if config_factory is None:
            from qwen3_tts_gguf.inference import TTSConfig

            config_factory = TTSConfig
        return config_factory(
            max_steps=max_new_tokens,
            temperature=0.6,
            sub_temperature=0.6,
            seed=42,
            sub_seed=45,
            streaming=streaming,
        )

    def _clone(
        self,
        text: str,
        *,
        language: str,
        max_new_tokens: int,
        streaming: bool,
    ) -> Any:
        if self._stream is None:
            raise RuntimeError("Qwen GGUF engine is not preloaded")
        result = self._stream.clone(
            text=text,
            language=language,
            zero_shot=False,
            config=self._config(
                streaming=streaming,
                max_new_tokens=max_new_tokens,
            ),
        )
        if result is None or result.audio is None or len(result.audio) == 0:
            raise RuntimeError("Qwen GGUF synthesis returned no audio")
        return result

    async def synthesize(self, text: str, **kwargs: Any) -> bytes:
        result = await asyncio.to_thread(
            self._clone,
            text,
            language=str(kwargs.get("language", "Chinese")),
            max_new_tokens=int(kwargs.get("max_new_tokens", 512)),
            streaming=False,
        )
        pcm = self._float32_to_pcm16(result.audio)
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm)
        return output.getvalue()

    async def synthesize_stream(
        self,
        text: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        if self._stream is None:
            raise RuntimeError("Qwen GGUF engine is not preloaded")
        loop = asyncio.get_running_loop()
        chunks: asyncio.Queue[bytes | BaseException | object] = asyncio.Queue()
        accepting = threading.Event()
        accepting.set()

        def publish(samples: np.ndarray) -> None:
            if not accepting.is_set():
                return
            pcm = self._float32_to_pcm16(samples)
            if pcm:
                loop.call_soon_threadsafe(chunks.put_nowait, pcm)

        def run() -> None:
            self._stream.set_audio_chunk_callback(publish)
            try:
                self._clone(
                    text,
                    language=str(kwargs.get("language", "Chinese")),
                    max_new_tokens=int(kwargs.get("max_new_tokens", 512)),
                    streaming=True,
                )
            except BaseException as error:
                loop.call_soon_threadsafe(chunks.put_nowait, error)
            finally:
                self._stream.set_audio_chunk_callback(None)
                loop.call_soon_threadsafe(chunks.put_nowait, _STREAM_END)

        worker = asyncio.create_task(asyncio.to_thread(run))
        try:
            while True:
                item = await chunks.get()
                if item is _STREAM_END:
                    break
                if isinstance(item, BaseException):
                    raise item
                if not isinstance(item, bytes):
                    raise RuntimeError("GGUF stream returned a non-bytes PCM chunk")
                yield item
        finally:
            accepting.clear()
            await self._wait_for_worker(worker)

    @staticmethod
    async def _wait_for_worker(worker: asyncio.Task[None]) -> None:
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
                current = asyncio.current_task()
                if current is not None:
                    current.uncancel()
        await worker
        if cancelled:
            raise asyncio.CancelledError

    @staticmethod
    def _float32_to_pcm16(samples: np.ndarray) -> bytes:
        normalized = np.asarray(samples, dtype=np.float32)
        clipped = np.clip(normalized, -1.0, 1.0)
        return (clipped * 32767.0).astype("<i2").tobytes()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._engine is not None:
            await asyncio.to_thread(self._engine.shutdown)


def build_host_service_from_env(
    *,
    engine_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build the fixed host identity while keeping paths out of public status."""
    from .app import QwenServiceSettings, QwenTTSService

    model_dir = Path(
        os.environ.get(
            "QWEN_HOST_TTS_MODEL_DIR",
            r"D:\AnimaModelAuditions\qwen3-tts-1.7b-streaming-20260726\model-base",
        )
    )
    reference_audio = Path(
        os.environ.get(
            "QWEN_HOST_TTS_REFERENCE_AUDIO",
            str(_REFERENCE_AUDIO),
        )
    )
    expected_hash = os.environ.get(
        "QWEN_HOST_TTS_REFERENCE_SHA256",
        _REFERENCE_SHA256,
    ).upper()
    try:
        actual_hash = hashlib.sha256(reference_audio.read_bytes()).hexdigest().upper()
    except OSError as error:
        raise RuntimeError("Qwen host reference audio is unavailable") from error
    if actual_hash != expected_hash:
        raise RuntimeError("Qwen host reference audio identity mismatch")

    engine = GGUFHostEngine(
        model_dir=model_dir,
        reference_audio=reference_audio,
        reference_text=os.environ.get(
            "QWEN_HOST_TTS_REFERENCE_TEXT",
            _REFERENCE_TEXT,
        ),
        engine_factory=engine_factory,
    )
    settings = QwenServiceSettings(
        api_key=os.environ.get("QWEN_TTS_API_KEY", ""),
        provider="qwen3-tts-gguf-host",
        model="Qwen3-TTS-1.7B-Base",
        revision=_RUNTIME_COMMIT,
        voice=_VOICE,
        quantization="talker=Q5_K,predictor=Q8_0,onnx=FP16",
        runtime_commit=_RUNTIME_COMMIT,
        language="Chinese",
        response_format="wav",
        sample_rate=24000,
        synthesis_timeout_seconds=float(os.environ.get("QWEN_HOST_TTS_TIMEOUT_SECONDS", "120")),
        capacity_wait_seconds=float(os.environ.get("QWEN_HOST_TTS_CAPACITY_WAIT_SECONDS", "0.05")),
        max_concurrency=1,
        queue_capacity=2,
        max_new_tokens=int(os.environ.get("QWEN_HOST_TTS_MAX_NEW_TOKENS", "512")),
        warmup_enabled=True,
        warmup_text=os.environ.get(
            "QWEN_HOST_TTS_WARMUP_TEXT",
            "你好，今天也请多关照。",
        ),
        warmup_max_new_tokens=48,
    )
    return QwenTTSService(settings, engine)
