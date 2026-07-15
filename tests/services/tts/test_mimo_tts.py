"""Tests for Xiaomi MiMo TTS provider."""

from __future__ import annotations

import base64

import httpx
import pytest

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.tts import MimoTTSConfig
from animetta.services.tts.factory import TTSFactory
from animetta.services.tts.mimo_tts import MimoTTS


def unwrap_tracing_proxy(engine):
    return getattr(engine, "_target", engine)


def test_mimo_config_is_registered():
    assert ProviderRegistry.get_config("tts", "mimo") is MimoTTSConfig

    config = MimoTTSConfig(api_key="key-123")

    assert config.type == "mimo"
    assert config.model == "mimo-v2.5-tts"
    assert config.base_url == "https://api.xiaomimimo.com/v1"
    assert config.voice == "mimo_default"
    assert config.response_format == "wav"


def test_factory_creates_mimo_tts_provider():
    engine = TTSFactory.create("mimo-tts", api_key="key-123")

    assert isinstance(unwrap_tracing_proxy(engine), MimoTTS)


def test_token_plan_key_uses_token_plan_base_url_when_default():
    tts = MimoTTS(api_key="tp-test-key")

    assert tts.base_url == "https://token-plan-cn.xiaomimimo.com/v1"


@pytest.mark.asyncio
async def test_synthesize_posts_mimo_chat_completion_and_decodes_audio():
    requests: list[httpx.Request] = []
    audio = b"RIFFmimo-audio"

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "audio": {
                                "data": base64.b64encode(audio).decode("ascii"),
                            }
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.xiaomimimo.com/v1",
        transport=httpx.MockTransport(handler),
    )
    tts = MimoTTS(api_key="key-123", http_client=client)

    result = await tts.synthesize("今晚想听一首轻快的歌。")

    assert result == audio
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["api-key"] == "key-123"
    payload = base64_json_body(request)
    assert payload["model"] == "mimo-v2.5-tts"
    assert payload["messages"] == [{"role": "assistant", "content": "今晚想听一首轻快的歌。"}]
    assert payload["audio"] == {"format": "wav", "voice": "mimo_default"}
    assert payload["stream"] is False

    await tts.close()


@pytest.mark.asyncio
async def test_synthesize_can_include_style_prompt_and_write_output_path(tmp_path):
    audio = b"RIFFstyled-mimo-audio"

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = base64_json_body(request)
        assert payload["messages"] == [
            {"role": "user", "content": "温柔、困倦、像深夜电台。"},
            {"role": "assistant", "content": "你已经很努力了，今晚先休息吧。"},
        ]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "audio": {
                                "data": base64.b64encode(audio).decode("ascii"),
                            }
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.xiaomimimo.com/v1",
        transport=httpx.MockTransport(handler),
    )
    tts = MimoTTS(
        api_key="key-123",
        style_prompt="温柔、困倦、像深夜电台。",
        http_client=client,
    )
    output_path = tmp_path / "mimo.wav"

    result = await tts.synthesize("你已经很努力了，今晚先休息吧。", output_path)

    assert result == str(output_path)
    assert output_path.read_bytes() == audio

    await tts.close()


@pytest.mark.asyncio
async def test_missing_api_key_fails_before_network_call():
    tts = MimoTTS(api_key=None)

    with pytest.raises(ValueError, match="MIMO_API_KEY"):
        await tts.synthesize("你好")


def base64_json_body(request: httpx.Request) -> dict:
    return __import__("json").loads(request.content.decode("utf-8"))
