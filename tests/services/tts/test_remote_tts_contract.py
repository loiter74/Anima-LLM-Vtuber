from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts.remote import RemoteTTSConfig
from animetta.services.tts.factory import TTSFactory
from animetta.services.tts.remote_tts import (
    RemoteTTS,
    RemoteTTSAuthenticationError,
    RemoteTTSIdentityMismatchError,
    RemoteTTSNotReadyError,
    RemoteTTSProtocolError,
    RemoteTTSTimeoutError,
    RemoteTTSUpstreamError,
)

pytestmark = pytest.mark.provider_contract

EXPECTED_IDENTITY = {
    "ready": True,
    "service": "qwen-tts",
    "api_version": "v1",
    "provider": "qwen3-tts-gguf-host",
    "model": "Qwen3-TTS-1.7B-Base",
    "revision": "0eb32e283ee46b86820c67843abb04cf12bc58d7",
    "voice": "vivian-synthetic-zh",
    "sample_rate": 24000,
}


def valid_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\x00\x00" * 240)
    return buffer.getvalue()


VALID_WAV = valid_wav_bytes()


def remote_config(**overrides: Any) -> RemoteTTSConfig:
    values: dict[str, Any] = {
        "type": "remote",
        "api_key": "test-secret",
        "base_url": "http://127.0.0.1:8767",
        "provider": "qwen3-tts-gguf-host",
        "model": EXPECTED_IDENTITY["model"],
        "revision": EXPECTED_IDENTITY["revision"],
        "voice": "vivian-synthetic-zh",
        "response_format": "wav",
        "timeout_seconds": 0.25,
    }
    values.update(overrides)
    return RemoteTTSConfig.model_validate(values)


def client_for(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def identity_headers(*, request_id: str = "req-1", **overrides: str) -> dict[str, str]:
    headers = {
        "content-type": "audio/wav",
        "x-animetta-provider": "qwen3-tts-gguf-host",
        "x-animetta-model": str(EXPECTED_IDENTITY["model"]),
        "x-animetta-voice": "vivian-synthetic-zh",
        "x-request-id": request_id,
    }
    headers.update(overrides)
    return headers


def test_remote_config_and_service_are_registered() -> None:
    assert ProviderRegistry.get_config("tts", "remote") is RemoteTTSConfig
    assert ProviderRegistry.get_service_class("tts", "remote") is RemoteTTS


def test_remote_config_without_revision_constructs_service() -> None:
    service = RemoteTTS.from_config(remote_config(revision=None))

    assert service.revision is None


def test_factory_keeps_remote_type_separate_from_worker_provider() -> None:
    config = remote_config(language=None)

    tts = TTSFactory.create(
        config.type,
        **config.model_dump(exclude={"type"}),
        strict=True,
    )

    target = object.__getattribute__(tts, "_target")
    assert isinstance(target, RemoteTTS)
    assert target.provider == "qwen3-tts-gguf-host"
    assert target.language is None


async def test_matching_readiness_publishes_configured_and_resolved_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ready"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(200, json=EXPECTED_IDENTITY)

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    resolved = await tts.check_readiness()

    assert resolved == EXPECTED_IDENTITY
    assert tts.configured_identity == {
        "provider": "qwen3-tts-gguf-host",
        "model": EXPECTED_IDENTITY["model"],
        "revision": EXPECTED_IDENTITY["revision"],
        "voice": "vivian-synthetic-zh",
    }
    assert tts.resolved_identity == EXPECTED_IDENTITY
    await tts.close()


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("provider", "mimo"),
        ("model", "wrong-model"),
        ("revision", "wrong-revision"),
        ("voice", "vivian"),
    ],
)
async def test_readiness_rejects_identity_mismatch(field: str, wrong_value: str) -> None:
    payload = {**EXPECTED_IDENTITY, field: wrong_value}
    client = client_for(lambda request: httpx.Response(200, json=payload))
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSIdentityMismatchError) as exc_info:
        await tts.check_readiness()

    assert exc_info.value.category == "identity_mismatch"
    assert "test-secret" not in str(exc_info.value)
    await tts.close()


async def test_readiness_rejects_dependency_not_ready() -> None:
    client = client_for(
        lambda request: httpx.Response(
            503,
            json={"ready": False, "category": "model_unavailable"},
        )
    )
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSNotReadyError) as exc_info:
        await tts.check_readiness()

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
    await tts.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", None),
        ("service", "wrong-service"),
        ("api_version", None),
        ("api_version", "v2"),
    ],
)
async def test_readiness_rejects_missing_or_incompatible_service_contract(
    field: str,
    value: str | None,
) -> None:
    payload = dict(EXPECTED_IDENTITY)
    if value is None:
        payload.pop(field)
    else:
        payload[field] = value
    client = client_for(lambda request: httpx.Response(200, json=payload))
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSProtocolError) as exc_info:
        await tts.check_readiness()

    assert exc_info.value.category == "incompatible_contract"
    assert field in str(exc_info.value)
    await tts.close()


async def test_synthesize_validates_request_and_response_identity(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = request.read().decode()
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            content=VALID_WAV,
            headers=identity_headers(request_id="turn-42"),
        )

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)
    output_path = tmp_path / "host.wav"

    result = await tts.synthesize(
        "你好，世界",
        output_path=output_path,
        language="Chinese",
        request_id="turn-42",
    )

    assert result == str(output_path)
    assert output_path.read_bytes() == VALID_WAV
    assert seen["path"] == "/v1/audio/speech"
    assert '"model":"Qwen3-TTS-1.7B-Base"' in seen["payload"]
    assert '"voice":"vivian-synthetic-zh"' in seen["payload"]
    assert '"input":"你好，世界"' in seen["payload"]
    assert seen["authorization"] == "Bearer test-secret"
    await tts.close()


async def test_synthesize_stream_requests_and_validates_pcm_chunks() -> None:
    pcm = b"\x01\x00" * 120
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            content=pcm,
            headers={
                **identity_headers(request_id="stream-1"),
                "content-type": "audio/pcm",
                "x-animetta-audio-format": "pcm_s16le",
                "x-animetta-sample-rate": "24000",
                "x-animetta-channels": "1",
            },
        )

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    chunks = [
        chunk
        async for chunk in tts.synthesize_stream(
            "流式你好",
            language="Chinese",
            request_id="stream-1",
        )
    ]

    assert b"".join(chunks) == pcm
    assert seen["payload"]["stream"] is True
    assert seen["payload"]["response_format"] == "wav"
    await tts.close()


async def test_synthesize_rejects_local_voice_or_model_override() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSIdentityMismatchError):
        await tts.synthesize("hello", voice="mimo_default")
    with pytest.raises(RemoteTTSIdentityMismatchError):
        await tts.synthesize("hello", model="wrong-model")

    assert called is False
    await tts.close()


@pytest.mark.parametrize(
    ("status", "error_type", "category", "retryable"),
    [
        (401, RemoteTTSAuthenticationError, "authentication", False),
        (400, RemoteTTSProtocolError, "request_rejected", False),
        (429, RemoteTTSUpstreamError, "busy", True),
        (500, RemoteTTSUpstreamError, "upstream_failure", True),
    ],
)
async def test_synthesize_maps_http_failures(
    status: int,
    error_type: type[Exception],
    category: str,
    retryable: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("animetta.services.tts.remote_tts.asyncio.sleep", sleep)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json={"category": category, "detail": "safe message", "request_id": "req-1"},
        )

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(error_type) as exc_info:
        await tts.synthesize("hello", request_id="req-1")

    error = exc_info.value
    assert getattr(error, "category") == category
    assert getattr(error, "retryable") is retryable
    assert getattr(error, "request_id") == "req-1"
    if status == 429:
        assert [call.args[0] for call in sleep.await_args_list] == [0.5, 1.0, 2.0]
        assert len(requests) == 4
    else:
        assert sleep.await_count == 0
        assert len(requests) == 1
    await tts.close()


async def test_synthesize_retries_typed_busy_with_same_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                429,
                json={"category": "busy", "request_id": payload["request_id"]},
            )
        return httpx.Response(
            200,
            content=VALID_WAV,
            headers=identity_headers(request_id=payload["request_id"]),
        )

    sleep = AsyncMock()
    monkeypatch.setattr("animetta.services.tts.remote_tts.asyncio.sleep", sleep)
    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    result = await tts.synthesize("恢复 Alice 音频", request_id="stable-request")

    assert result == VALID_WAV
    assert [request["request_id"] for request in requests] == [
        "stable-request",
        "stable-request",
    ]
    sleep.assert_awaited_once_with(0.5)
    await tts.close()


async def test_synthesize_maps_network_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-bearing upstream detail", request=request)

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSTimeoutError) as exc_info:
        await tts.synthesize("hello", request_id="timeout-1")

    assert exc_info.value.category == "timeout"
    assert exc_info.value.request_id == "timeout-1"
    assert "secret-bearing" not in str(exc_info.value)
    await tts.close()


async def test_synthesize_normalizes_untrusted_remote_error_category() -> None:
    malicious = "busy\nC:/private/alice.wav worker-secret"
    client = client_for(
        lambda request: httpx.Response(
            503,
            json={"category": malicious, "request_id": "req-1"},
        )
    )
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSUpstreamError) as exc_info:
        await tts.synthesize("hello", request_id="req-1")

    assert exc_info.value.category == "upstream_failure"
    assert malicious not in str(exc_info.value)
    assert "private" not in exc_info.value.category
    await tts.close()


@pytest.mark.parametrize(
    ("content", "headers", "message"),
    [
        (b"", identity_headers(), "empty"),
        (b"not-audio", identity_headers(**{"content-type": "application/json"}), "content type"),
        (VALID_WAV, identity_headers(**{"x-animetta-provider": "mimo"}), "provider"),
        (VALID_WAV, identity_headers(**{"x-animetta-model": "wrong"}), "model"),
        (VALID_WAV, identity_headers(**{"x-animetta-voice": "vivian"}), "voice"),
        (VALID_WAV, identity_headers(request_id="other"), "request ID"),
    ],
)
async def test_synthesize_rejects_malformed_or_crossed_response(
    content: bytes,
    headers: dict[str, str],
    message: str,
) -> None:
    client = client_for(lambda request: httpx.Response(200, content=content, headers=headers))
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises((RemoteTTSProtocolError, RemoteTTSIdentityMismatchError)) as exc_info:
        await tts.synthesize("hello", request_id="req-1")

    assert message.lower() in str(exc_info.value).lower()
    await tts.close()


async def test_synthesize_rejects_non_empty_but_undecodable_wav() -> None:
    client = client_for(
        lambda request: httpx.Response(
            200,
            content=b"RIFF-not-a-decodable-wave",
            headers=identity_headers(),
        )
    )
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    with pytest.raises(RemoteTTSProtocolError) as exc_info:
        await tts.synthesize("hello", request_id="req-1")

    assert exc_info.value.category == "invalid_audio"
    assert "decodable wav" in str(exc_info.value).lower()
    await tts.close()


async def test_empty_input_returns_no_audio_without_network_call() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = client_for(handler)
    tts = RemoteTTS.from_config(remote_config(), http_client=client)

    assert await tts.synthesize("  ") == b""
    assert called is False
    await tts.close()
