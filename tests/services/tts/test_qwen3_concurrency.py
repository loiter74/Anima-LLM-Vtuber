from __future__ import annotations

import asyncio
import gc
import sys
import threading
import wave
from concurrent.futures import Future
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from loguru import logger

from animetta.services.tts.qwen3_tts import Qwen3TTSTTS


@pytest.fixture(autouse=True)
def _fake_soundfile(monkeypatch: pytest.MonkeyPatch):
    def write(target, _audio_data, _sample_rate, **_kwargs) -> None:
        payload = b"RIFF\x00\x00\x00\x00WAVE"
        if hasattr(target, "write"):
            target.write(payload)
        else:
            Path(target).write_bytes(payload)

    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=write))


def _write_valid_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24_000)
        wav_file.writeframes(b"\x00\x00" * 32)


async def _wait_for_thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 2.0), "worker did not reach synchronization point"


class _FakeVoiceCloneModel:
    def __init__(self) -> None:
        self.prompt_calls = 0
        self.prompt_threads: list[int] = []
        self.generation_threads: list[int] = []
        self.generated_texts: list[str] = []
        self._prompt = [object()]

    def create_voice_clone_prompt(self, **_kwargs):
        self.prompt_calls += 1
        self.prompt_threads.append(threading.get_ident())
        return self._prompt

    def generate_voice_clone(self, *, text: str, **_kwargs):
        self.generation_threads.append(threading.get_ident())
        self.generated_texts.append(text)
        return ([np.zeros(32, dtype=np.float32)], 24_000)


class _HarnessQwen(Qwen3TTSTTS):
    def __init__(
        self,
        reference: Path,
        model: _FakeVoiceCloneModel,
        *,
        load_started: threading.Event | None = None,
        load_release: threading.Event | None = None,
    ) -> None:
        super().__init__(
            device="cpu",
            ref_audio_path=str(reference),
            ref_text="Alice reference transcript",
            x_vector_only=False,
        )
        self.fake_model = model
        self.load_calls = 0
        self.load_threads: list[int] = []
        self.load_started = load_started
        self.load_release = load_release

    def _load_model(self) -> None:
        self.load_calls += 1
        self.load_threads.append(threading.get_ident())
        if self.load_started is not None:
            self.load_started.set()
        if self.load_release is not None:
            assert self.load_release.wait(2.0), "test did not release model loading"
        self._model = self.fake_model
        self._loaded = True


class _SerializationProbeModel(_FakeVoiceCloneModel):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0
        self._call_count = 0
        self.second_entered = threading.Event()

    def generate_voice_clone(self, *, text: str, **_kwargs):
        with self._lock:
            self._call_count += 1
            call_number = self._call_count
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            self.generated_texts.append(text)

        if call_number == 1:
            self.second_entered.wait(0.5)
        else:
            self.second_entered.set()

        with self._lock:
            self._active -= 1
        return ([np.zeros(32, dtype=np.float32)], 24_000)


class _BlockingModel(_FakeVoiceCloneModel):
    def __init__(self) -> None:
        super().__init__()
        self.blocked_started = threading.Event()
        self.blocked_release = threading.Event()
        self.next_started = threading.Event()

    def generate_voice_clone(self, *, text: str, **_kwargs):
        self.generation_threads.append(threading.get_ident())
        self.generated_texts.append(text)
        if text == "blocked":
            self.blocked_started.set()
            assert self.blocked_release.wait(2.0), "test did not release blocked synthesis"
        if text == "next":
            self.next_started.set()
        return ([np.zeros(32, dtype=np.float32)], 24_000)


class _FailOnceModel(_FakeVoiceCloneModel):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate_voice_clone(self, *, text: str, **_kwargs):
        self.generation_threads.append(threading.get_ident())
        self.calls += 1
        self.generated_texts.append(text)
        if self.calls == 1:
            raise RuntimeError("isolated synthesis failure")
        return ([np.zeros(32, dtype=np.float32)], 24_000)


async def test_preload_loads_and_builds_clone_prompt_on_same_background_worker(
    tmp_path: Path,
):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _FakeVoiceCloneModel()
    load_started = threading.Event()
    load_release = threading.Event()
    provider = _HarnessQwen(
        reference,
        model,
        load_started=load_started,
        load_release=load_release,
    )
    event_loop_thread = threading.get_ident()

    preload_task = asyncio.create_task(provider.preload())
    await _wait_for_thread_event(load_started)
    loop_tick = asyncio.Event()
    asyncio.get_running_loop().call_soon(loop_tick.set)
    await asyncio.wait_for(loop_tick.wait(), timeout=1.0)
    assert not preload_task.done()

    load_release.set()
    await preload_task

    assert provider.load_threads == model.prompt_threads
    assert provider.load_threads[0] != event_loop_thread
    assert model.prompt_calls == 1
    assert provider._voice_clone_prompt is model._prompt
    assert provider.preload_status == {"state": "ready", "ready": True, "error": None}

    await provider.synthesize("worker identity")

    assert provider.load_threads == model.prompt_threads == model.generation_threads
    await provider.close()


async def test_queued_preload_cannot_reverse_closing_state(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _FakeVoiceCloneModel()
    load_started = threading.Event()
    load_release = threading.Event()
    provider = _HarnessQwen(
        reference,
        model,
        load_started=load_started,
        load_release=load_release,
    )
    blocker_started = threading.Event()
    blocker_release = threading.Event()

    def block_worker() -> None:
        blocker_started.set()
        assert blocker_release.wait(2.0), "test did not release worker blocker"

    blocker = provider._submit_worker(block_worker)
    await _wait_for_thread_event(blocker_started)
    preload_task = asyncio.create_task(provider.preload())
    await asyncio.sleep(0)
    close_task = asyncio.create_task(provider.close())
    await asyncio.sleep(0)

    assert provider.preload_status == {"state": "closing", "ready": False, "error": None}
    try:
        blocker_release.set()
        await _wait_for_thread_event(load_started)
        assert provider.preload_status == {
            "state": "closing",
            "ready": False,
            "error": None,
        }
    finally:
        blocker_release.set()
        load_release.set()
        with suppress(Exception):
            await asyncio.wrap_future(blocker)
        with suppress(Exception):
            await preload_task
        with suppress(Exception):
            await close_task

    assert provider.preload_status == {"state": "closed", "ready": False, "error": None}


async def test_queued_lazy_synthesis_cannot_reverse_closing_state(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _BlockingModel()
    model.next_release = threading.Event()
    load_started = threading.Event()
    load_release = threading.Event()
    provider = _HarnessQwen(
        reference,
        model,
        load_started=load_started,
        load_release=load_release,
    )
    blocker_started = threading.Event()
    blocker_release = threading.Event()

    original_generate = model.generate_voice_clone

    def generate_and_block(*, text: str, **kwargs):
        result = original_generate(text=text, **kwargs)
        if text == "next":
            assert model.next_release.wait(2.0), "test did not release lazy synthesis"
        return result

    model.generate_voice_clone = generate_and_block

    def block_worker() -> None:
        blocker_started.set()
        assert blocker_release.wait(2.0), "test did not release worker blocker"

    provider._submit_worker(block_worker)
    await _wait_for_thread_event(blocker_started)
    lazy_synthesis = asyncio.create_task(provider.synthesize("next"))
    await asyncio.sleep(0)
    close_task = asyncio.create_task(provider.close())
    await asyncio.sleep(0)

    assert provider.preload_status == {"state": "closing", "ready": False, "error": None}
    try:
        blocker_release.set()
        await _wait_for_thread_event(load_started)
        assert provider.preload_status == {
            "state": "closing",
            "ready": False,
            "error": None,
        }

        load_release.set()
        await _wait_for_thread_event(model.next_started)
        assert provider.preload_status == {
            "state": "closing",
            "ready": False,
            "error": None,
        }
    finally:
        blocker_release.set()
        load_release.set()
        model.next_release.set()

    audio = await lazy_synthesis
    await close_task

    assert audio.startswith(b"RIFF")
    assert provider.preload_status == {"state": "closed", "ready": False, "error": None}


async def test_concurrent_synthesis_is_serialized_by_one_provider_worker(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _SerializationProbeModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()

    first, second = await asyncio.gather(
        provider.synthesize("first"),
        provider.synthesize("second"),
    )

    assert first.startswith(b"RIFF")
    assert second.startswith(b"RIFF")
    assert model.max_active == 1
    assert model.prompt_calls == 1
    await provider.close()


async def test_wait_for_cancellation_keeps_running_work_in_flight_and_next_job_queued(
    tmp_path: Path,
):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _BlockingModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()

    running = asyncio.create_task(provider.synthesize("blocked"))
    await _wait_for_thread_event(model.blocked_started)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(running, timeout=0.01)

    assert not provider._synth_done.is_set()
    next_request = asyncio.create_task(provider.synthesize("next"))
    assert not await asyncio.to_thread(model.next_started.wait, 0.05)

    model.blocked_release.set()
    next_audio = await next_request

    assert next_audio.startswith(b"RIFF")
    assert model.generated_texts == ["blocked", "next"]
    assert provider._synth_done.is_set()
    await provider.close()


async def test_cancelled_queued_request_never_generates_stale_audio(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _BlockingModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()

    running = asyncio.create_task(provider.synthesize("blocked"))
    await _wait_for_thread_event(model.blocked_started)
    stale = asyncio.create_task(provider.synthesize("stale"))
    await asyncio.sleep(0)

    stale.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale

    model.blocked_release.set()
    await running
    await provider.synthesize("fresh")

    assert model.generated_texts == ["blocked", "fresh"]
    await provider.close()


async def test_cancelled_close_continues_cleanup_after_all_submitted_work(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _BlockingModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()
    running = asyncio.create_task(provider.synthesize("blocked"))
    await _wait_for_thread_event(model.blocked_started)

    close_task = asyncio.create_task(provider.close())
    await asyncio.sleep(0)
    close_future: Future[None] = provider._close_future

    try:
        assert provider.preload_status == {
            "state": "closing",
            "ready": False,
            "error": None,
        }
        with pytest.raises(RuntimeError, match="closing"):
            await provider.synthesize("late")
        assert provider._model is model

        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        assert provider._model is model
    finally:
        model.blocked_release.set()
        with suppress(asyncio.CancelledError):
            await running

    await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(close_future)), timeout=2.0)

    assert provider._model is None
    assert provider._loaded is False
    assert provider._voice_clone_prompt is None
    assert provider.preload_status == {"state": "closed", "ready": False, "error": None}
    await provider.close()


async def test_close_cleanup_runs_after_running_and_already_queued_synthesis(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _BlockingModel()
    queued_release = threading.Event()
    provider = _HarnessQwen(reference, model)
    await provider.preload()
    original_generate = model.generate_voice_clone

    def generate_with_queued_barrier(*, text: str, **kwargs):
        result = original_generate(text=text, **kwargs)
        if text == "next":
            assert queued_release.wait(2.0), "test did not release queued synthesis"
        return result

    model.generate_voice_clone = generate_with_queued_barrier
    running = asyncio.create_task(provider.synthesize("blocked"))
    await _wait_for_thread_event(model.blocked_started)
    queued = asyncio.create_task(provider.synthesize("next"))
    await asyncio.sleep(0)
    close_task = asyncio.create_task(provider.close())
    await asyncio.sleep(0)

    assert provider.preload_status == {"state": "closing", "ready": False, "error": None}
    model.blocked_release.set()
    await _wait_for_thread_event(model.next_started)

    assert provider._model is model
    assert provider.preload_status == {"state": "closing", "ready": False, "error": None}

    queued_release.set()
    await asyncio.gather(running, queued)
    await close_task

    assert model.generated_texts == ["blocked", "next"]
    assert provider._model is None
    assert provider.preload_status == {"state": "closed", "ready": False, "error": None}


async def test_synthesis_failure_does_not_poison_worker_or_cached_prompt(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _FailOnceModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()

    with pytest.raises(RuntimeError, match="isolated synthesis failure"):
        await provider.synthesize("fails")

    recovered = await provider.synthesize("recovers")

    assert recovered.startswith(b"RIFF")
    assert model.generated_texts == ["fails", "recovers"]
    assert model.prompt_calls == 1
    assert provider.preload_status == {"state": "ready", "ready": True, "error": None}
    await provider.close()


async def test_cancelled_preload_waiter_drains_late_worker_exception(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    load_started = threading.Event()
    load_release = threading.Event()
    failed_state = threading.Event()

    class LateFailingPreload(Qwen3TTSTTS):
        def _load_model(self) -> None:
            load_started.set()
            assert load_release.wait(2.0), "test did not release failing preload"
            raise RuntimeError("late preload failure")

        def _set_preload_state(self, state: str, error: Exception | None = None) -> None:
            super()._set_preload_state(state, error)
            if state == "failed":
                failed_state.set()

    provider = LateFailingPreload(
        device="cpu",
        ref_audio_path=str(reference),
        ref_text="Alice reference transcript",
        x_vector_only=False,
    )
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    exception_contexts: list[dict] = []
    loop.set_exception_handler(lambda _loop, context: exception_contexts.append(context))

    try:
        preload_task = asyncio.create_task(provider.preload())
        await _wait_for_thread_event(load_started)
        preload_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await preload_task

        load_release.set()
        await _wait_for_thread_event(failed_state)
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)

        assert callable(getattr(provider, "_await_worker_future", None))
        assert not any(
            context.get("message") == "Future exception was never retrieved"
            for context in exception_contexts
        )
    finally:
        load_release.set()
        loop.set_exception_handler(previous_handler)
        await provider.close()


async def test_cancelled_close_waiter_drains_late_worker_exception():
    close_started = threading.Event()
    close_release = threading.Event()
    close_done = threading.Event()

    class LateFailingClose(Qwen3TTSTTS):
        def _close_worker(self) -> None:
            close_started.set()
            assert close_release.wait(2.0), "test did not release failing close"
            raise RuntimeError("late close failure")

    provider = LateFailingClose(device="cpu")
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    exception_contexts: list[dict] = []
    loop.set_exception_handler(lambda _loop, context: exception_contexts.append(context))

    try:
        close_task = asyncio.create_task(provider.close())
        await _wait_for_thread_event(close_started)
        provider._close_future.add_done_callback(lambda _future: close_done.set())
        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task

        close_release.set()
        await _wait_for_thread_event(close_done)
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)

        assert callable(getattr(provider, "_await_worker_future", None))
        assert not any(
            context.get("message") == "Future exception was never retrieved"
            for context in exception_contexts
        )
    finally:
        close_release.set()
        loop.set_exception_handler(previous_handler)


async def test_audio_encoding_runs_on_serial_worker_without_blocking_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _FakeVoiceCloneModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()
    encoding_started = threading.Event()
    encoding_release = threading.Event()
    loop_tick = threading.Event()
    loop_tick_observed: list[bool] = []
    encoding_threads: list[int] = []

    def write(target, _audio_data, _sample_rate, **_kwargs) -> None:
        encoding_threads.append(threading.get_ident())
        encoding_started.set()
        assert encoding_release.wait(2.0), "test did not release audio encoding"
        target.write(b"RIFF\x00\x00\x00\x00WAVE")

    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=write))
    loop = asyncio.get_running_loop()

    def observe_loop() -> None:
        assert encoding_started.wait(2.0), "audio encoding never started"
        loop.call_soon_threadsafe(loop_tick.set)
        loop_tick_observed.append(loop_tick.wait(0.5))
        encoding_release.set()

    observer = threading.Thread(target=observe_loop, daemon=True)
    observer.start()
    try:
        audio = await provider.synthesize("encoding worker")
    finally:
        encoding_release.set()
        observer.join(timeout=2.0)

    assert not observer.is_alive()
    assert audio.startswith(b"RIFF")
    assert loop_tick_observed == [True]
    assert encoding_threads == provider.load_threads
    await provider.close()


async def test_output_write_remains_in_flight_until_close_can_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _FakeVoiceCloneModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()
    output_path = tmp_path / "new-output-directory" / "voice.wav"
    output_write_started = threading.Event()
    output_write_release = threading.Event()
    output_write_timed_out = threading.Event()
    write_threads: list[int] = []

    def write(target, _audio_data, _sample_rate, **_kwargs) -> None:
        write_threads.append(threading.get_ident())
        payload = b"RIFF\x00\x00\x00\x00WAVE"
        if hasattr(target, "write"):
            target.write(payload)
            return
        output_write_started.set()
        if not output_write_release.wait(1.0):
            output_write_timed_out.set()
        Path(target).write_bytes(payload)

    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(write=write))
    synthesis_task = asyncio.create_task(
        provider.synthesize("file output", output_path=output_path)
    )
    close_task: asyncio.Task | None = None
    try:
        await _wait_for_thread_event(output_write_started)
        close_task = asyncio.create_task(provider.close())
        await asyncio.sleep(0)

        assert not output_write_timed_out.is_set()
        assert provider._model is model
        assert provider.preload_status == {
            "state": "closing",
            "ready": False,
            "error": None,
        }
    finally:
        output_write_release.set()

    result = await synthesis_task
    assert close_task is not None
    await close_task

    assert result == str(output_path)
    assert output_path.read_bytes().startswith(b"RIFF")
    assert write_threads == [provider.load_threads[0], provider.load_threads[0]]
    assert provider._model is None


async def test_logs_do_not_expose_reference_or_output_paths(tmp_path: Path):
    reference = tmp_path / "sensitive-ref-marker.wav"
    _write_valid_wav(reference)
    output_path = tmp_path / "sensitive-output-marker" / "voice.wav"
    model = _FakeVoiceCloneModel()
    provider = _HarnessQwen(reference, model)
    messages: list[object] = []
    sink_id = logger.add(messages.append, format="{message}")

    try:
        await provider.preload()
        await provider.synthesize("safe logging", output_path=output_path)
        await provider.close()
    finally:
        logger.remove(sink_id)

    rendered = "".join(str(message) for message in messages)
    assert "sensitive-ref-marker" not in rendered
    assert "sensitive-output-marker" not in rendered


async def test_failure_log_contains_only_exception_type_not_raw_message(tmp_path: Path):
    reference = tmp_path / "alice.wav"
    _write_valid_wav(reference)
    model = _FakeVoiceCloneModel()
    provider = _HarnessQwen(reference, model)
    await provider.preload()
    sensitive_marker = "sensitive-runtime-error-marker"

    def fail_generation(**_kwargs):
        raise RuntimeError(sensitive_marker)

    model.generate_voice_clone = fail_generation
    messages: list[object] = []
    sink_id = logger.add(messages.append, format="{message}")

    try:
        with pytest.raises(RuntimeError, match=sensitive_marker):
            await provider.synthesize("failure logging")
    finally:
        logger.remove(sink_id)
        await provider.close()

    rendered = "".join(str(message) for message in messages)
    assert sensitive_marker not in rendered
    assert "RuntimeError" in rendered
