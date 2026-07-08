"""Tests for Xiaomi MiMo ASR provider."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.asr import MimoASRConfig
from animetta.services.asr.factory import ASRFactory
from animetta.services.asr.mimo_asr import MimoASR


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


def json_body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


def test_mimo_asr_config_is_registered() -> None:
    assert ProviderRegistry.get_config("asr", "mimo") is MimoASRConfig

    config = MimoASRConfig(api_key="key-123")

    assert config.type == "mimo"
    assert config.model == "mimo-v2.5-asr"
    assert config.base_url == "https://api.xiaomimimo.com/v1"
    assert config.language == "auto"
    assert config.sample_rate == 16000
    assert config.input_audio_format == "pcm_s16le"


def test_factory_creates_mimo_asr_alias() -> None:
    engine = ASRFactory.create("mimo-asr", api_key="key-123")

    assert isinstance(unwrap_tracing_proxy(engine), MimoASR)


def test_token_plan_key_uses_token_plan_base_url_when_default() -> None:
    asr = MimoASR(api_key="tp-test-key")

    assert asr.base_url == "https://token-plan-cn.xiaomimimo.com/v1"


@pytest.mark.asyncio
async def test_transcribe_wraps_raw_pcm_as_wav_and_posts_mimo_chat_completion() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "你好，世界"}}]},
        )

    client = httpx.AsyncClient(
        base_url="https://api.xiaomimimo.com/v1",
        transport=httpx.MockTransport(handler),
    )
    asr = MimoASR(api_key="key-123", http_client=client)

    text = await asr.transcribe(b"\x01\x00" * 1600)

    assert text == "你好，世界"
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["api-key"] == "key-123"
    payload = json_body(request)
    assert payload["model"] == "mimo-v2.5-asr"
    assert payload["asr_options"] == {"language": "auto"}
    assert payload["stream"] is False
    audio_part = payload["messages"][0]["content"][0]
    assert audio_part["type"] == "input_audio"
    assert audio_part["input_audio"]["data"].startswith("data:audio/wav;base64,")

    await asr.close()


@pytest.mark.asyncio
async def test_transcribe_path_infers_audio_format(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    path = tmp_path / "sample.mp3"
    path.write_bytes(b"ID3mimo-audio")

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "path text"}}]})

    client = httpx.AsyncClient(
        base_url="https://api.xiaomimimo.com/v1",
        transport=httpx.MockTransport(handler),
    )
    asr = MimoASR(api_key="key-123", http_client=client)

    text = await asr.transcribe(path)

    assert text == "path text"
    audio_part = json_body(requests[0])["messages"][0]["content"][0]
    assert audio_part["input_audio"]["data"].startswith("data:audio/mp3;base64,")

    await asr.close()


@pytest.mark.asyncio
async def test_missing_api_key_fails_before_network_call() -> None:
    asr = MimoASR(api_key=None)

    with pytest.raises(ValueError, match="MIMO_API_KEY"):
        await asr.transcribe(b"\x00\x00")
