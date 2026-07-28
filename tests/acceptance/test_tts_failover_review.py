from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from animetta.services.tts.failover_tts import FailoverTTS
from animetta.services.tts.remote_tts import RemoteTTSError


class BillingPrimary:
    provider_identity = "dashscope"

    async def preload(self) -> None:
        raise RemoteTTSError("billing", category="billing", retryable=False)

    async def synthesize_stream(self, text: str, **kwargs: object) -> AsyncIterator[bytes]:
        del text, kwargs
        if False:
            yield b""

    async def close(self) -> None:
        return None


class PCMStreamingFallback:
    provider_identity = "qwen3-tts-gguf-host"

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = [b"\x01\x00" * 2400] if chunks is None else chunks
        self.closed = 0
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def preload(self) -> None:
        return None

    async def synthesize_stream(self, text: str, **kwargs: object) -> AsyncIterator[bytes]:
        self.calls.append((text, kwargs))
        for chunk in self.chunks:
            yield chunk

    async def close(self) -> None:
        self.closed += 1


def make_harness(tmp_path: Path, fallback: PCMStreamingFallback | None = None):
    from animetta.acceptance.tts_failover_review import TTSFailoverReviewHarness

    fallback = fallback or PCMStreamingFallback()
    engine = FailoverTTS(primary=BillingPrimary(), fallback=fallback)
    clock_values = iter((1.0, 1.02, 1.03))
    return (
        TTSFailoverReviewHarness(
            engine=engine,
            token="review-secret",
            artifact_dir=tmp_path,
            clock=lambda: next(clock_values),
            timeout_seconds=0.5,
        ),
        fallback,
    )


async def test_billing_failure_streams_fixed_local_wav_and_safe_report(tmp_path: Path) -> None:
    harness, fallback = make_harness(tmp_path)
    await harness.prepare()

    result = await harness.run(
        scene_id="billing-to-local",
        authorization="Bearer review-secret",
    )
    assert fallback.calls[-1][0] == (
        "晚上好，欢迎来到直播间。云端语音暂时不可用，现在由本小姐继续为你播报。"
    )

    assert "text" not in result.report
    assert result.report["actual_backend"] == "fallback"
    assert result.report["primary_error_category"] == "billing"
    assert result.report["readiness"]["ready"] is True
    assert result.report["readiness"]["degraded"] is True
    assert result.report["readiness"]["active_backend"] == "fallback"
    assert result.report["sample_rate"] == 24000
    assert result.report["channels"] == 1
    assert result.report["sample_width_bytes"] == 2
    assert result.report["pcm_bytes"] == 4800
    assert result.report["complete"] is True
    assert result.report["first_audio_seconds"] == pytest.approx(0.02)
    assert result.report["rtf"] == pytest.approx(0.3)
    assert "review-secret" not in str(result.report)
    assert str(tmp_path) not in str(result.report)
    assert "mouth_timeline" not in result.report
    assert len(result.mouth_timeline) == 5
    assert all(0.0 <= volume <= 1.0 for volume in result.mouth_timeline)
    assert any(volume > 0.0 for volume in result.mouth_timeline)

    with wave.open(io.BytesIO(result.wav_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == 24000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.readframes(wav_file.getnframes()) == b"\x01\x00" * 2400


@pytest.mark.parametrize(
    ("scene_id", "text", "emotion"),
    [
        ("live2d-calm", "晚上好，今天也一起轻松聊聊天吧。", "neutral"),
        ("live2d-annoyed", "哼，这种事情居然还要本小姐提醒你吗？", "angry"),
        ("live2d-surprised", "诶？这是真的吗？完全没想到会变成这样！", "surprised"),
    ],
)
async def test_live2d_scenes_use_fixed_emotion_matched_text(
    tmp_path: Path,
    scene_id: str,
    text: str,
    emotion: str,
) -> None:
    harness, fallback = make_harness(tmp_path)
    await harness.prepare()

    result = await harness.run(scene_id=scene_id, authorization="Bearer review-secret")

    actual_text, kwargs = fallback.calls[-1]
    assert actual_text == text
    assert kwargs["emotion"] == emotion
    assert isinstance(kwargs["instruction"], str)
    assert kwargs["instruction"]
    assert result.report["scene_id"] == scene_id


async def test_harness_rejects_invalid_token_and_unknown_scene(tmp_path: Path) -> None:
    from animetta.acceptance.tts_failover_review import (
        ReviewAuthorizationError,
        ReviewSceneError,
    )

    harness, _fallback = make_harness(tmp_path)
    await harness.prepare()

    with pytest.raises(ReviewAuthorizationError):
        await harness.run(scene_id="billing-to-local", authorization="Bearer wrong")
    with pytest.raises(ReviewSceneError):
        await harness.run(scene_id="different", authorization="Bearer review-secret")


async def test_harness_disables_fallback_with_non_24khz_resolved_identity(
    tmp_path: Path,
) -> None:
    from animetta.acceptance.tts_failover_review import ReviewIdentityError

    fallback = PCMStreamingFallback()
    fallback.resolved_identity = {
        "provider": "qwen3-tts-gguf-host",
        "model": "Qwen3-TTS-1.7B-Base",
        "voice": "tosaka-rin-cn",
        "sample_rate": 16000,
    }
    harness, _fallback = make_harness(tmp_path, fallback)

    with pytest.raises(ReviewIdentityError):
        await harness.prepare()


async def test_harness_rejects_odd_or_empty_pcm(tmp_path: Path) -> None:
    from animetta.acceptance.tts_failover_review import ReviewAudioError

    for chunks in ([b"\x01"], []):
        harness, _fallback = make_harness(tmp_path, PCMStreamingFallback(chunks=chunks))
        await harness.prepare()
        with pytest.raises(ReviewAudioError):
            await harness.run(
                scene_id="billing-to-local",
                authorization="Bearer review-secret",
            )


async def test_harness_returns_busy_for_overlapping_attempt(tmp_path: Path) -> None:
    from animetta.acceptance.tts_failover_review import ReviewBusyError

    gate = asyncio.Event()

    class BlockingFallback(PCMStreamingFallback):
        async def synthesize_stream(self, text: str, **kwargs: object) -> AsyncIterator[bytes]:
            del text, kwargs
            await gate.wait()
            yield b"\x00\x00" * 2400

    harness, _fallback = make_harness(tmp_path, BlockingFallback())
    await harness.prepare()
    running = asyncio.create_task(
        harness.run(scene_id="billing-to-local", authorization="Bearer review-secret")
    )
    await asyncio.sleep(0)
    with pytest.raises(ReviewBusyError):
        await harness.run(
            scene_id="billing-to-local",
            authorization="Bearer review-secret",
        )
    gate.set()
    await running


async def test_harness_times_out_and_close_is_idempotent(tmp_path: Path) -> None:
    from animetta.acceptance.tts_failover_review import ReviewTimeoutError

    class NeverFallback(PCMStreamingFallback):
        async def synthesize_stream(self, text: str, **kwargs: object) -> AsyncIterator[bytes]:
            del text, kwargs
            await asyncio.Future()
            yield b""

    fallback = NeverFallback()
    harness, _fallback = make_harness(tmp_path, fallback)
    harness.timeout_seconds = 0.01
    await harness.prepare()

    with pytest.raises(ReviewTimeoutError):
        await harness.run(
            scene_id="billing-to-local",
            authorization="Bearer review-secret",
        )
    await harness.close()
    await harness.close()
    assert fallback.closed == 1


def test_real_harness_pins_the_confirmed_fallback_identity(tmp_path: Path) -> None:
    from animetta.acceptance.tts_failover_review import FALLBACK_IDENTITY, create_real_harness

    harness = create_real_harness(
        port=18123,
        token="review-secret",
        fallback_token="fallback-secret",
        artifact_dir=tmp_path,
    )
    fallback = harness.engine.fallback

    assert fallback.configured_identity == {
        "provider": FALLBACK_IDENTITY["provider"],
        "model": FALLBACK_IDENTITY["model"],
        "revision": FALLBACK_IDENTITY["revision"],
        "voice": FALLBACK_IDENTITY["voice"],
        "quantization": FALLBACK_IDENTITY["quantization"],
        "runtime_commit": FALLBACK_IDENTITY["runtime_commit"],
    }
    assert fallback.base_url == "http://127.0.0.1:8767"
    assert fallback.api_key == "fallback-secret"


async def test_review_app_requires_auth_and_returns_safe_artifact_urls(tmp_path: Path) -> None:
    from animetta.acceptance.tts_failover_review import create_review_app

    harness, _fallback = make_harness(tmp_path)
    app = create_review_app(harness)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://review") as client:
        unauthorized = await client.post("/ready")
        assert unauthorized.status_code == 401
        assert unauthorized.json() == {"category": "authentication"}

        ready = await client.post(
            "/ready",
            headers={"authorization": "Bearer review-secret"},
        )
        assert ready.status_code == 200
        assert ready.json()["readiness"]["active_backend"] == "fallback"

        response = await client.post(
            "/v1/review/synthesize",
            headers={"authorization": "Bearer review-secret"},
            json={"scene_id": "billing-to-local", "text": "must be ignored"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["audio_wav"].startswith("/artifacts/tts-failover-")
        assert payload["backend_report"].startswith("/artifacts/tts-failover-")
        assert len(payload["mouth_timeline"]) == 5
        assert all(0.0 <= volume <= 1.0 for volume in payload["mouth_timeline"])
        assert "mouth_timeline" not in payload["report"]
        assert "review-secret" not in str(payload)
        audio = await client.get(payload["audio_wav"])
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/wav")
