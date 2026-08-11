from __future__ import annotations

from typing import Any

from scripts.benchmark_host_tts import HOST_TTS_CONTRACT, _synthesize_once


class _Response:
    headers = {
        "content-type": "audio/pcm",
        "x-animetta-audio-format": "pcm_s16le",
        "x-animetta-sample-rate": "24000",
        "x-animetta-channels": "1",
    }

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_raw(self):
        yield b"\x00\x00" * 24_000


class _Client:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    def stream(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.request = {"method": method, "url": url, **kwargs}
        return _Response()


def test_benchmark_uses_the_versioned_host_identity_contract() -> None:
    client = _Client()

    result = _synthesize_once(
        client,  # type: ignore[arg-type]
        url="http://127.0.0.1:8767",
        token="secret",
        text="你好",
    )

    assert client.request is not None
    assert client.request["json"] == {
        "model": HOST_TTS_CONTRACT.model,
        "voice": HOST_TTS_CONTRACT.voice,
        "input": "你好",
        "language": HOST_TTS_CONTRACT.language,
        "response_format": HOST_TTS_CONTRACT.response_format,
        "stream": True,
    }
    assert result["audio_bytes"] == 48_000
