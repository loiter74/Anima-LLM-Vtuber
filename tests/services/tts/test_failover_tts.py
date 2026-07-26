from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from animetta.services.tts.failover_tts import (
    FailoverTTS,
    FailoverTTSUnavailableError,
)
from animetta.services.tts.remote_tts import RemoteTTSError


def provider_error(category: str, *, retryable: bool) -> RemoteTTSError:
    return RemoteTTSError(
        "sanitized provider failure",
        category=category,
        retryable=retryable,
    )


class FakeTTS:
    def __init__(self, name: str) -> None:
        self.name = name
        self.preload_error: BaseException | None = None
        self.stream_plans: list[list[bytes | BaseException]] = [[b"\x01\x00"]]
        self.stream_calls = 0
        self.synthesize_calls = 0
        self.synthesize_error: BaseException | None = None
        self.close_calls = 0
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def preload(self) -> None:
        if self.preload_error is not None:
            raise self.preload_error

    async def synthesize_stream(
        self,
        text: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        del text, kwargs
        index = min(self.stream_calls, len(self.stream_plans) - 1)
        self.stream_calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        for item in self.stream_plans[index]:
            if isinstance(item, BaseException):
                raise item
            yield item

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        **kwargs: Any,
    ) -> bytes | str:
        del text, kwargs
        self.synthesize_calls += 1
        if self.synthesize_error is not None:
            raise self.synthesize_error
        audio = self.name.encode()
        if output_path is None:
            return audio
        path = Path(output_path)
        path.write_bytes(audio)
        return str(path)

    async def close(self) -> None:
        self.close_calls += 1

    @property
    def audio_format(self) -> str:
        return "pcm_s16le"

    @property
    def sample_rate(self) -> int:
        return 24000


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def service(
    primary: FakeTTS,
    fallback: FakeTTS,
    clock: Clock | None = None,
) -> FailoverTTS:
    return FailoverTTS(
        primary=primary,
        fallback=fallback,
        cooldown_seconds=300.0,
        primary_pre_audio_retries=1,
        clock=clock,
    )


async def collect(tts: FailoverTTS) -> bytes:
    return b"".join([chunk async for chunk in tts.synthesize_stream("你好", instruction="温柔")])


@pytest.mark.parametrize(
    ("primary_ok", "fallback_ok"), [(True, True), (True, False), (False, True)]
)
async def test_preload_succeeds_when_either_backend_is_ready(
    primary_ok: bool,
    fallback_ok: bool,
) -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    if not primary_ok:
        primary.preload_error = provider_error("billing", retryable=False)
    if not fallback_ok:
        fallback.preload_error = provider_error("connection", retryable=True)
    tts = service(primary, fallback)

    await tts.preload()

    snapshot = tts.readiness_snapshot()
    assert snapshot["ready"] is True
    assert snapshot["degraded"] is not (primary_ok and fallback_ok)


async def test_preload_fails_only_when_both_backends_fail() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.preload_error = provider_error("billing", retryable=False)
    fallback.preload_error = provider_error("connection", retryable=True)

    with pytest.raises(FailoverTTSUnavailableError):
        await service(primary, fallback).preload()


async def test_retryable_primary_failure_before_first_chunk_retries_once() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.stream_plans = [
        [provider_error("connection", retryable=True)],
        [b"\x11\x00", b"\x12\x00"],
    ]
    tts = service(primary, fallback)
    await tts.preload()

    audio = await collect(tts)

    assert audio == b"\x11\x00\x12\x00"
    assert primary.stream_calls == 2
    assert fallback.stream_calls == 0
    assert tts.actual_backend == "primary"


async def test_non_retryable_primary_failure_switches_to_fallback_immediately() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.stream_plans = [[provider_error("billing", retryable=False)]]
    fallback.stream_plans = [[b"\x21\x00"]]
    tts = service(primary, fallback)
    await tts.preload()

    audio = await collect(tts)

    assert audio == b"\x21\x00"
    assert primary.stream_calls == 1
    assert fallback.stream_calls == 1
    assert tts.actual_backend == "fallback"
    assert tts.readiness_snapshot()["circuit"]["state"] == "open"
    assert tts.metrics_snapshot()["switch_reasons"] == {"billing": 1}
    assert "fallback" in tts.metrics_snapshot()["first_audio_seconds"]
    assert "fallback" in tts.metrics_snapshot()["rtf"]


async def test_real_fallback_failure_invalidates_cached_readiness_until_recovery() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.preload_error = provider_error("billing", retryable=False)
    fallback.stream_plans = [[provider_error("connection", retryable=True)], [b"\x22\x00"]]
    tts = service(primary, fallback)
    await tts.preload()

    with pytest.raises(RemoteTTSError):
        await collect(tts)

    failed = tts.readiness_snapshot()
    assert failed["ready"] is False
    assert failed["fallback"] == {
        "ready": False,
        "error_category": "connection",
    }

    assert await collect(tts) == b"\x22\x00"
    recovered = tts.readiness_snapshot()
    assert recovered["ready"] is True
    assert recovered["fallback"] == {
        "ready": True,
        "error_category": None,
    }


async def test_non_streaming_fallback_failure_updates_cached_readiness() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.preload_error = provider_error("billing", retryable=False)
    fallback.synthesize_error = provider_error("timeout", retryable=True)
    tts = service(primary, fallback)
    await tts.preload()

    with pytest.raises(RemoteTTSError):
        await tts.synthesize("你好")

    assert tts.readiness_snapshot()["fallback"] == {
        "ready": False,
        "error_category": "timeout",
    }


async def test_failure_after_first_chunk_never_switches_current_utterance() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.stream_plans = [[b"\x31\x00", provider_error("connection", retryable=True)]]
    fallback.stream_plans = [[b"\x32\x00"]]
    tts = service(primary, fallback)
    await tts.preload()

    received: list[bytes] = []
    with pytest.raises(RemoteTTSError):
        async for chunk in tts.synthesize_stream("第一句", instruction="温柔"):
            received.append(chunk)

    assert received == [b"\x31\x00"]
    assert fallback.stream_calls == 0
    assert await collect(tts) == b"\x32\x00"


async def test_half_open_probe_is_single_flight_and_full_success_recovers() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    clock = Clock()
    primary.stream_plans = [
        [provider_error("billing", retryable=False)],
        [b"\x41\x00", b"\x42\x00"],
        [b"\x43\x00"],
    ]
    fallback.stream_plans = [[b"\x51\x00"]]
    tts = service(primary, fallback, clock)
    await tts.preload()
    assert await collect(tts) == b"\x51\x00"

    clock.now += 301
    primary.started = asyncio.Event()
    primary.release = asyncio.Event()
    probe = asyncio.create_task(collect(tts))
    await primary.started.wait()
    concurrent = await collect(tts)
    primary.release.set()

    assert concurrent == b"\x51\x00"
    assert await probe == b"\x41\x00\x42\x00"
    assert tts.readiness_snapshot()["circuit"]["state"] == "closed"
    primary.started = None
    primary.release = None
    assert await collect(tts) == b"\x43\x00"


async def test_cancellation_does_not_switch_voice_or_trip_breaker() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    primary.started = asyncio.Event()
    primary.release = asyncio.Event()
    tts = service(primary, fallback)
    await tts.preload()

    task = asyncio.create_task(collect(tts))
    await primary.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fallback.stream_calls == 0
    assert tts.readiness_snapshot()["circuit"]["state"] == "closed"


async def test_close_owns_both_children_once() -> None:
    primary = FakeTTS("primary")
    fallback = FakeTTS("fallback")
    tts = service(primary, fallback)

    await tts.close()
    await tts.close()

    assert primary.close_calls == 1
    assert fallback.close_calls == 1
