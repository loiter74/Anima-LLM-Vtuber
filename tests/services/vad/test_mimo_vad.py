from __future__ import annotations

from typing import Any

import numpy as np

from animetta.config.core.registry import ProviderRegistry
from animetta.config.providers.vad.mimo import MimoVADConfig
from animetta.services.vad.factory import VADFactory
from animetta.services.vad.interface import VADState
from animetta.services.vad.mimo_vad import MimoVAD


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _Client:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.posts: list[dict[str, Any]] = []
        self.closed = False

    def post(self, path: str, *, headers: dict[str, str], json: dict[str, Any]) -> _Response:
        self.posts.append({"path": path, "headers": headers, "json": json})
        return _Response(self.payload)

    def close(self) -> None:
        self.closed = True


def _speech_chunk() -> np.ndarray:
    return np.ones(1600, dtype=np.float32) * 0.5


def _silence_chunk() -> np.ndarray:
    return np.zeros(1600, dtype=np.float32)


def test_mimo_vad_config_is_registered() -> None:
    assert ProviderRegistry.get_config("vad", "mimo") is MimoVADConfig


def test_factory_creates_mimo_vad_alias() -> None:
    vad = VADFactory.create(
        "mimo-vad",
        api_key="test-key",
        confirm_with_asr=False,
    )

    assert isinstance(vad, MimoVAD)
    assert vad.get_current_state() == VADState.IDLE


def test_token_plan_key_uses_token_plan_base_url_when_default() -> None:
    vad = MimoVAD(api_key="tp-test-key", confirm_with_asr=False)

    assert vad.base_url == "https://token-plan-cn.xiaomimimo.com/v1"


def test_mimo_vad_posts_asr_once_on_speech_end() -> None:
    client = _Client({"choices": [{"message": {"content": "hello"}}]})
    vad = MimoVAD(
        api_key="test-key",
        http_client=client,
        sample_rate=16000,
        db_threshold=-50,
        min_speech_duration=1,
        min_silence_duration=1,
    )

    start = vad.detect_speech(_speech_chunk())
    assert start.is_speech_start is True
    assert client.posts == []

    end = vad.detect_speech(_silence_chunk())

    assert end.is_speech_end is True
    assert end.speech_detected is True
    assert len(client.posts) == 1
    request = client.posts[0]
    assert request["path"] == "/chat/completions"
    assert request["headers"]["api-key"] == "test-key"
    assert request["json"]["model"] == "mimo-v2.5-asr"
    assert request["json"]["asr_options"] == {"language": "auto"}
    audio_part = request["json"]["messages"][0]["content"][0]
    assert audio_part["type"] == "input_audio"
    assert audio_part["input_audio"]["data"].startswith("data:audio/wav;base64,")


def test_mimo_vad_marks_empty_asr_as_unconfirmed() -> None:
    client = _Client({"choices": [{"message": {"content": ""}}]})
    vad = MimoVAD(
        api_key="test-key",
        http_client=client,
        sample_rate=16000,
        db_threshold=-50,
        min_speech_duration=1,
        min_silence_duration=1,
    )

    vad.detect_speech(_speech_chunk())
    result = vad.detect_speech(_silence_chunk())

    assert result.is_speech_end is True
    assert result.speech_detected is False
    assert result.metadata["asr_text_len"] == 0


def test_mimo_vad_can_skip_asr_confirmation() -> None:
    client = _Client({"choices": [{"message": {"content": ""}}]})
    vad = MimoVAD(
        api_key=None,
        http_client=client,
        confirm_with_asr=False,
        sample_rate=16000,
        db_threshold=-50,
        min_speech_duration=1,
        min_silence_duration=1,
    )

    vad.detect_speech(_speech_chunk())
    result = vad.detect_speech(_silence_chunk())

    assert result.is_speech_end is True
    assert result.speech_detected is True
    assert client.posts == []


async def test_mimo_vad_close_closes_sync_client() -> None:
    client = _Client({"choices": [{"message": {"content": "hello"}}]})
    vad = MimoVAD(
        api_key="test-key",
        http_client=client,
        confirm_with_asr=False,
    )

    await vad.close()

    assert client.closed is True
