from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

import httpx
import pytest

from animetta_qwen_tts.app import (
    QwenServiceSettings,
    QwenTTSService,
    create_app,
)

pytestmark = pytest.mark.provider_contract

TEST_PROVIDER = "test-provider"
TEST_MODEL = "test-model"
TEST_REVISION = "test-revision"
TEST_VOICE = "test-voice"
TEST_QUANTIZATION = "test-quantization"
TEST_RUNTIME_COMMIT = "test-runtime-commit"


def valid_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\x00\x00" * 240)
    return buffer.getvalue()


VALID_WAV = valid_wav_bytes()


class FakeQwenEngine:
    def __init__(self, audio: bytes = VALID_WAV) -> None:
        self.audio = audio
        self.stream_chunks = [b"\x01\x00" * 64, b"\x02\x00" * 64]
        self.preload_calls = 0
        self.synthesize_calls: list[dict[str, Any]] = []
        self.synthesize_stream_calls: list[dict[str, Any]] = []
        self.closed = False
        self.error: Exception | None = None
        self.stream_error: Exception | None = None
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def preload(self) -> None:
        self.preload_calls += 1

    async def synthesize(self, text: str, **kwargs: Any) -> bytes:
        self.synthesize_calls.append({"text": text, **kwargs})
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.audio

    async def synthesize_stream(self, text: str, **kwargs: Any) -> Any:
        self.synthesize_stream_calls.append({"text": text, **kwargs})
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        for chunk in self.stream_chunks:
            yield chunk
        if self.stream_error is not None:
            raise self.stream_error

    async def close(self) -> None:
        self.closed = True


def settings(**overrides: Any) -> QwenServiceSettings:
    values: dict[str, Any] = {
        "api_key": "worker-secret",
        "provider": TEST_PROVIDER,
        "model": TEST_MODEL,
        "revision": TEST_REVISION,
        "voice": TEST_VOICE,
        "language": "Chinese",
        "response_format": "wav",
        "sample_rate": 24000,
        "synthesis_timeout_seconds": 0.25,
        "capacity_wait_seconds": 0.01,
        "max_concurrency": 1,
        "max_new_tokens": 48,
        "warmup_enabled": False,
    }
    values.update(overrides)
    return QwenServiceSettings(**values)


def app_for(
    engine: FakeQwenEngine,
    *,
    service_settings: QwenServiceSettings | None = None,
) -> tuple[Any, QwenTTSService]:
    service = QwenTTSService(service_settings or settings(), engine)
    return create_app(service=service, preload_on_startup=False), service


def auth_headers() -> dict[str, str]:
    return {"authorization": "Bearer worker-secret"}


async def request(app: Any, method: str, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://worker") as client:
        return await client.request(method, path, **kwargs)


def speech_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "model": TEST_MODEL,
        "voice": TEST_VOICE,
        "input": "你好，爱丽丝",
        "response_format": "wav",
        "language": "Chinese",
        "request_id": "turn-7",
    }
    payload.update(overrides)
    return payload


async def test_health_is_cheap_and_does_not_preload_or_synthesize() -> None:
    engine = FakeQwenEngine()
    app, _ = app_for(engine)

    response = await request(app, "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "qwen-tts",
        "api_version": "v1",
    }
    assert engine.preload_calls == 0
    assert engine.synthesize_calls == []


async def test_ready_is_cached_and_identity_is_unavailable_before_preload() -> None:
    engine = FakeQwenEngine()
    app, _ = app_for(engine)

    first = await request(app, "GET", "/ready", headers=auth_headers())
    second = await request(app, "GET", "/v1/identity", headers=auth_headers())

    assert first.status_code == 503
    assert first.json() == {
        "ready": False,
        "service": "qwen-tts",
        "api_version": "v1",
        "category": "not_ready",
    }
    assert second.status_code == 503
    assert engine.preload_calls == 0


async def test_preload_publishes_exact_ready_and_identity_contracts() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(engine)
    await service.preload()

    ready = await request(app, "GET", "/ready", headers=auth_headers())
    identity = await request(app, "GET", "/v1/identity", headers=auth_headers())

    expected = {
        "ready": True,
        "service": "qwen-tts",
        "api_version": "v1",
        **settings().identity_fields(),
    }
    assert ready.status_code == 200
    assert ready.json() == expected
    assert identity.status_code == 200
    assert identity.json() == expected
    assert engine.preload_calls == 1


async def test_identity_includes_fixed_host_runtime_metadata_when_configured() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(
        engine,
        service_settings=settings(
            quantization=TEST_QUANTIZATION,
            runtime_commit=TEST_RUNTIME_COMMIT,
        ),
    )
    await service.preload()

    identity = await request(app, "GET", "/v1/identity", headers=auth_headers())

    assert identity.status_code == 200
    assert identity.json()["quantization"] == TEST_QUANTIZATION
    assert identity.json()["runtime_commit"] == TEST_RUNTIME_COMMIT


async def test_preload_warms_generation_before_publishing_readiness() -> None:
    engine = FakeQwenEngine()
    _, service = app_for(
        engine,
        service_settings=settings(
            warmup_enabled=True,
            warmup_text="你好，我是爱丽丝。",
            warmup_max_new_tokens=128,
        ),
    )

    await service.preload()

    assert service.identity()["ready"] is True
    assert engine.preload_calls == 1
    assert engine.synthesize_calls == [
        {
            "text": "你好，我是爱丽丝。",
            "language": "Chinese",
            "max_new_tokens": 128,
        }
    ]


async def test_preload_failure_is_sanitized_and_never_becomes_ready() -> None:
    class FailingEngine(FakeQwenEngine):
        async def preload(self) -> None:
            self.preload_calls += 1
            raise RuntimeError("C:/private/alice.wav worker-secret")

    engine = FailingEngine()
    app, service = app_for(engine)

    with pytest.raises(RuntimeError):
        await service.preload()
    response = await request(app, "GET", "/ready", headers=auth_headers())

    assert response.status_code == 503
    assert response.json()["category"] == "preload_failed"
    assert "private" not in response.text
    assert "worker-secret" not in response.text


async def test_valid_speech_returns_audio_and_correlated_identity_headers() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(),
    )

    assert response.status_code == 200
    assert response.content == VALID_WAV
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-animetta-provider"] == TEST_PROVIDER
    assert response.headers["x-animetta-model"] == settings().model
    assert response.headers["x-animetta-voice"] == TEST_VOICE
    assert response.headers["x-request-id"] == "turn-7"
    assert engine.synthesize_calls == [
        {
            "text": "你好，爱丽丝",
            "language": "Chinese",
            "max_new_tokens": 48,
        }
    ]


async def test_streaming_speech_returns_ordered_pcm16_chunks_and_identity_headers() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(stream=True),
    )

    assert response.status_code == 200
    assert response.content == b"".join(engine.stream_chunks)
    assert response.headers["content-type"] == "audio/pcm"
    assert response.headers["x-animetta-audio-format"] == "pcm_s16le"
    assert response.headers["x-animetta-sample-rate"] == "24000"
    assert response.headers["x-animetta-channels"] == "1"
    assert response.headers["x-animetta-provider"] == TEST_PROVIDER
    assert response.headers["x-animetta-model"] == settings().model
    assert response.headers["x-animetta-voice"] == TEST_VOICE
    assert response.headers["x-request-id"] == "turn-7"
    assert engine.synthesize_stream_calls == [
        {
            "text": "你好，爱丽丝",
            "language": "Chinese",
            "max_new_tokens": 48,
        }
    ]
    assert engine.synthesize_calls == []


@pytest.mark.parametrize("chunks", [[], [b""], [b"\x01"]])
async def test_streaming_rejects_empty_or_odd_first_pcm_chunk(
    chunks: list[bytes],
) -> None:
    engine = FakeQwenEngine()
    engine.stream_chunks = chunks
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(stream=True),
    )

    assert response.status_code == 502
    assert response.json() == {
        "category": "invalid_audio",
        "request_id": "turn-7",
    }


async def test_interactive_synthesis_forwards_bounded_codec_token_budget() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(
        engine,
        service_settings=settings(max_new_tokens=48),
    )
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(input="短句"),
    )

    assert response.status_code == 200
    assert engine.synthesize_calls == [
        {
            "text": "短句",
            "language": "Chinese",
            "max_new_tokens": 48,
        }
    ]


async def test_interactive_synthesis_scales_and_caps_codec_budget_by_text() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(
        engine,
        service_settings=settings(max_new_tokens=512),
    )
    await service.preload()

    for text in (
        "你好，我是爱丽丝。",
        "今天我们讨论一个完全不同的技术主题，并确认语音不会在四秒时被截断。",
        "长" * 200,
    ):
        response = await request(
            app,
            "POST",
            "/v1/audio/speech",
            headers=auth_headers(),
            json=speech_payload(input=text),
        )
        assert response.status_code == 200

    short_budget, sentence_budget, capped_budget = [
        call["max_new_tokens"] for call in engine.synthesize_calls
    ]
    assert 48 <= short_budget < sentence_budget < 512
    assert capped_budget == 512


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"model": "wrong-model"}, "model"),
        ({"voice": "vivian"}, "voice"),
        ({"language": "English"}, "language"),
        ({"response_format": "mp3"}, "response_format"),
        ({"input": "  "}, "input"),
    ],
)
async def test_unsupported_speech_identity_is_typed_4xx_without_generation(
    overrides: dict[str, Any],
    field: str,
) -> None:
    engine = FakeQwenEngine()
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(**overrides),
    )

    assert response.status_code == 422
    assert response.json() == {
        "category": "unsupported_identity",
        "field": field,
        "request_id": "turn-7",
    }
    assert engine.synthesize_calls == []


@pytest.mark.parametrize("path", ["/ready", "/v1/identity", "/v1/audio/speech"])
async def test_protected_contract_rejects_missing_or_wrong_auth(path: str) -> None:
    engine = FakeQwenEngine()
    app, service = app_for(engine)
    await service.preload()
    method = "POST" if path.endswith("speech") else "GET"
    kwargs = {"json": speech_payload()} if method == "POST" else {}

    missing = await request(app, method, path, **kwargs)
    wrong = await request(
        app,
        method,
        path,
        headers={"authorization": "Bearer wrong"},
        **kwargs,
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json() == {"category": "authentication"}
    assert "worker-secret" not in missing.text + wrong.text
    assert engine.synthesize_calls == []


async def test_invalid_json_is_typed_and_does_not_leak_parser_details() -> None:
    engine = FakeQwenEngine()
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers={**auth_headers(), "content-type": "application/json"},
        content=b"{invalid",
    )

    assert response.status_code == 400
    assert response.json()["category"] == "invalid_request"
    assert engine.synthesize_calls == []


@pytest.mark.parametrize(
    ("error", "status", "category"),
    [
        (RuntimeError("private model failure"), 502, "generation_failed"),
        (TimeoutError(), 504, "timeout"),
    ],
)
async def test_generation_failure_is_typed_and_sanitized(
    error: Exception,
    status: int,
    category: str,
) -> None:
    engine = FakeQwenEngine()
    engine.error = error
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(),
    )

    assert response.status_code == status
    assert response.json() == {"category": category, "request_id": "turn-7"}
    assert "private model failure" not in response.text


async def test_empty_generated_audio_is_a_typed_failure() -> None:
    engine = FakeQwenEngine(audio=b"")
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(),
    )

    assert response.status_code == 502
    assert response.json() == {
        "category": "invalid_audio",
        "request_id": "turn-7",
    }


async def test_malformed_non_empty_generated_audio_is_a_typed_failure() -> None:
    engine = FakeQwenEngine(audio=b"RIFF-not-a-decodable-wave")
    app, service = app_for(engine)
    await service.preload()

    response = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(),
    )

    assert response.status_code == 502
    assert response.json() == {
        "category": "invalid_audio",
        "request_id": "turn-7",
    }


async def test_warmup_rejects_malformed_non_empty_audio_and_never_becomes_ready() -> None:
    engine = FakeQwenEngine(audio=b"RIFF-not-a-decodable-wave")
    app, service = app_for(
        engine,
        service_settings=settings(warmup_enabled=True),
    )

    with pytest.raises(RuntimeError, match="valid audio"):
        await service.preload()

    response = await request(app, "GET", "/ready", headers=auth_headers())
    assert response.status_code == 503
    assert response.json()["category"] == "preload_failed"


async def test_capacity_is_bounded_and_request_identities_do_not_cross() -> None:
    engine = FakeQwenEngine()
    engine.started = asyncio.Event()
    engine.release = asyncio.Event()
    app, service = app_for(engine)
    await service.preload()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://worker") as client:
        first_task = asyncio.create_task(
            client.post(
                "/v1/audio/speech",
                headers=auth_headers(),
                json=speech_payload(request_id="first"),
            )
        )
        await engine.started.wait()
        second = await client.post(
            "/v1/audio/speech",
            headers=auth_headers(),
            json=speech_payload(request_id="second"),
        )
        engine.release.set()
        first = await first_task

    assert second.status_code == 429
    assert second.json() == {"category": "busy", "request_id": "second"}
    assert first.status_code == 200
    assert first.headers["x-request-id"] == "first"
    assert len(engine.synthesize_calls) == 1


async def test_host_queue_admits_two_fifo_waiters_and_rejects_the_next() -> None:
    engine = FakeQwenEngine()
    engine.started = asyncio.Event()
    engine.release = asyncio.Event()
    _, service = app_for(
        engine,
        service_settings=settings(queue_capacity=2),
    )
    await service.preload()

    first = asyncio.create_task(service.synthesize(speech_payload(request_id="first")))
    await engine.started.wait()
    second = asyncio.create_task(service.synthesize(speech_payload(request_id="second")))
    third = asyncio.create_task(service.synthesize(speech_payload(request_id="third")))
    await asyncio.sleep(0)
    rejected = await service.synthesize(speech_payload(request_id="fourth"))

    assert rejected.status_code == 429
    assert rejected.body == b'{"category":"busy","request_id":"fourth"}'

    engine.release.set()
    responses = await asyncio.gather(first, second, third)

    assert [response.headers["x-request-id"] for response in responses] == [
        "first",
        "second",
        "third",
    ]
    assert [call["text"] for call in engine.synthesize_calls] == [
        "你好，爱丽丝",
        "你好，爱丽丝",
        "你好，爱丽丝",
    ]


async def test_timeout_keeps_capacity_reserved_until_gpu_work_finishes() -> None:
    engine = FakeQwenEngine()
    engine.started = asyncio.Event()
    engine.release = asyncio.Event()
    app, service = app_for(
        engine,
        service_settings=settings(synthesis_timeout_seconds=0.01),
    )
    await service.preload()

    first = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(request_id="timed-out"),
    )
    second = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(request_id="while-running"),
    )

    assert first.status_code == 504
    assert first.json() == {"category": "timeout", "request_id": "timed-out"}
    assert second.status_code == 429
    assert second.json() == {"category": "busy", "request_id": "while-running"}

    engine.release.set()
    for _ in range(20):
        if not service._capacity.locked():
            break
        await asyncio.sleep(0)
    recovered = await request(
        app,
        "POST",
        "/v1/audio/speech",
        headers=auth_headers(),
        json=speech_payload(request_id="recovered"),
    )

    assert recovered.status_code == 200
    assert recovered.headers["x-request-id"] == "recovered"
    assert [call["text"] for call in engine.synthesize_calls] == [
        "你好，爱丽丝",
        "你好，爱丽丝",
    ]


async def test_request_cancellation_keeps_capacity_reserved_until_gpu_work_finishes() -> None:
    engine = FakeQwenEngine()
    engine.started = asyncio.Event()
    engine.release = asyncio.Event()
    _, service = app_for(engine)
    await service.preload()

    cancelled = asyncio.create_task(service.synthesize(speech_payload(request_id="cancelled")))
    await engine.started.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    assert service._capacity.locked()
    while_running = await service.synthesize(speech_payload(request_id="while-running"))
    assert while_running.status_code == 429

    engine.release.set()
    for _ in range(20):
        if not service._capacity.locked():
            break
        await asyncio.sleep(0)

    recovered = await service.synthesize(speech_payload(request_id="recovered"))
    assert recovered.status_code == 200
    assert [call["text"] for call in engine.synthesize_calls] == [
        "你好，爱丽丝",
        "你好，爱丽丝",
    ]


async def test_close_delegates_to_engine_once() -> None:
    engine = FakeQwenEngine()
    _, service = app_for(engine)

    await service.close()
    await service.close()

    assert engine.closed is True
