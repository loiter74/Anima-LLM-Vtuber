from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.core.model_loading_manager import ModelLoadingManager
from animetta.core.service_context import ServiceContext
from animetta.core.service_pool import ServicePool
from animetta.observability.service_proxy import InstrumentedServiceProxy
from animetta.services.llm.mock_llm import MockLLM
from animetta.services.llm.openai_llm import OpenAILLM
from animetta.services.tts.mock_tts import MockTTS
from animetta.services.tts.qwen3_tts import Qwen3TTSTTS
from animetta.tracing.proxy import TracingProxy


class _DeepSeek(OpenAILLM):
    """Dependency-free real-provider double retaining the production type."""

    def __init__(self) -> None:
        self._provider_identity = "deepseek"
        self.model = "deepseek-v4-flash"
        self.extra_body = {"thinking": {"type": "disabled"}}
        self.api_key = "super-secret-api-key"
        self.base_url = "https://api.deepseek.com/v1"


class _AliceQwen(Qwen3TTSTTS):
    """Dependency-free Qwen double retaining the production type."""

    def __init__(
        self,
        state: str = "ready",
        *,
        ready: bool | None = None,
        error: str | None = None,
    ) -> None:
        self.model = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        self.speaker = "custom"
        self.ref_audio_path = "config/personas/voices/alice_ref.wav"
        self.ref_text = "the Alice reference transcript must never be serialized"
        self.x_vector_only = False
        self._status = {
            "state": state,
            "ready": state == "ready" if ready is None else ready,
            "error": error,
        }

    @property
    def preload_status(self) -> dict[str, str | bool | None]:
        return dict(self._status)


class _BrokenAliceQwen(_AliceQwen):
    @property
    def preload_status(self) -> dict[str, str | bool | None]:
        raise RuntimeError("credential=https://user:password@example.invalid?key=secret")


def _config(profile: str = "golden") -> SimpleNamespace:
    return SimpleNamespace(
        system=SimpleNamespace(runtime_profile=profile),
        services=SimpleNamespace(agent="deepseek", tts="alice_vc"),
        agent=SimpleNamespace(
            llm_config=SimpleNamespace(
                type="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com/v1",
                thinking="disabled",
            )
        ),
        tts=SimpleNamespace(
            type="qwen3",
            model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            ref_audio_path="config/personas/voices/alice_ref.wav",
            ref_text="the Alice reference transcript must never be serialized",
            x_vector_only=False,
        ),
    )


def _frontend(ready: bool) -> dict[str, str | bool | None]:
    return {
        "state": "ready" if ready else "failed",
        "ready": ready,
        "reason": None if ready else "assets_missing",
    }


def _manager(tts_state: str = "loaded") -> SimpleNamespace:
    return SimpleNamespace(get_status=lambda: {"tts": tts_state})


@pytest.fixture(autouse=True)
def _reset_pool_state() -> None:
    from animetta.inspection.checks import health as health_checks

    previous_connectivity_cache = dict(health_checks._llm_connectivity_cache)
    health_checks._llm_connectivity_cache = {"ok": None, "status": "pending"}
    ServicePool._llm = None
    ServicePool._tts = None
    ServicePool._asr = None
    ServicePool._ready = False
    ServicePool._ctx = None
    for name, value in (
        ("_runtime_config", None),
        ("_model_manager", None),
        ("_init_state", "pending"),
        ("_init_error", None),
        ("_initializing_task", None),
        ("_shutdown_task", None),
        ("_shutdown_requested", False),
        ("_shutdown_errors", ()),
        (
            "_llm_connectivity",
            {"state": "pending", "ready": False, "reason": None},
        ),
    ):
        setattr(ServicePool, name, value)
    yield
    ServicePool._llm = None
    ServicePool._tts = None
    ServicePool._asr = None
    ServicePool._ready = False
    ServicePool._ctx = None
    health_checks._llm_connectivity_cache = previous_connectivity_cache


def _seed_pool(
    *,
    config: SimpleNamespace | None = None,
    llm: object | None = None,
    tts: object | None = None,
    manager: object | None = None,
    connectivity: dict[str, object] | None = None,
) -> tuple[SimpleNamespace, object]:
    active_config = config or _config()
    active_manager = manager or _manager()
    ServicePool._runtime_config = active_config
    ServicePool._model_manager = active_manager
    ServicePool._init_state = "ready"
    ServicePool._llm = llm or _DeepSeek()
    ServicePool._tts = tts or _AliceQwen()
    ServicePool._llm_connectivity = connectivity or {
        "state": "ready",
        "ready": True,
        "reason": None,
        "latency_ms": 12.3,
    }
    return active_config, active_manager


def _snapshot(
    *,
    config: SimpleNamespace | None = None,
    manager: object | None = None,
    frontend_ready: bool = True,
) -> dict[str, object]:
    snapshot = ServicePool.get_readiness_snapshot(
        config=config,
        model_manager=manager,
        frontend=_frontend(frontend_ready),
    )
    return snapshot.to_dict()


def test_golden_snapshot_is_ready_only_for_real_deepseek_and_alice() -> None:
    config, manager = _seed_pool()

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["profile"] == "golden"
    assert payload["acceptance_eligible"] is True
    assert payload["components"]["llm"] == {
        "state": "ready",
        "ready": True,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "reason": None,
        "thinking": "disabled",
    }
    assert payload["components"]["tts"] == {
        "state": "ready",
        "ready": True,
        "provider": "qwen3",
        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "reason": None,
        "voice": "alice_vc",
        "clone_prompt_ready": True,
    }
    serialized = json.dumps(payload)
    assert "super-secret" not in serialized
    assert "password" not in serialized
    assert "reference transcript" not in serialized
    assert "config/personas" not in serialized


@pytest.mark.parametrize("state", ["pending", "loading", "closing", "closed"])
def test_golden_snapshot_rejects_non_ready_qwen_lifecycle(state: str) -> None:
    config, manager = _seed_pool(tts=_AliceQwen(state))

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["tts"]["state"] == state
    assert payload["components"]["tts"]["ready"] is False


def test_golden_snapshot_rejects_failed_preload_without_leaking_error() -> None:
    config, manager = _seed_pool(
        tts=_AliceQwen(
            "failed",
            error="https://user:password@example.invalid?api_key=secret",
        )
    )

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["tts"]["reason"] == "preload_failed"
    serialized = json.dumps(payload)
    assert "password" not in serialized
    assert "api_key" not in serialized


def test_golden_snapshot_rejects_connectivity_failure() -> None:
    config, manager = _seed_pool(
        connectivity={
            "state": "failed",
            "ready": False,
            "reason": "request_failed",
        }
    )

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["llm"]["reason"] == "request_failed"


@pytest.mark.parametrize(
    ("endpoint", "reason"),
    [
        (None, "endpoint_missing"),
        ("https://api.openai.com/v1", "endpoint_policy"),
        ("http://api.deepseek.com/v1", "endpoint_policy"),
    ],
)
def test_golden_snapshot_rejects_missing_or_non_deepseek_endpoint(
    endpoint: str | None,
    reason: str,
) -> None:
    llm = _DeepSeek()
    llm.base_url = endpoint
    config, manager = _seed_pool(llm=llm)

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["llm"]["reason"] == reason
    assert "api.openai.com" not in json.dumps(payload)


def test_golden_snapshot_rejects_configured_and_engine_endpoint_mismatch() -> None:
    llm = _DeepSeek()
    llm.base_url = "https://api.deepseek.com"
    config, manager = _seed_pool(llm=llm)

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["llm"]["reason"] == "endpoint_mismatch"


@pytest.mark.parametrize("identity", [None, "openai"])
def test_golden_snapshot_requires_factory_bound_deepseek_identity(
    identity: str | None,
) -> None:
    llm = _DeepSeek()
    llm._provider_identity = identity
    config, manager = _seed_pool(llm=llm)

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["llm"]["reason"] == "provider_identity"


@pytest.mark.parametrize("state", ["pending", "loading"])
def test_golden_snapshot_preserves_pending_connectivity_state(state: str) -> None:
    config, manager = _seed_pool(connectivity={"state": state, "ready": False, "reason": None})

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["llm"]["state"] == state
    assert payload["components"]["llm"]["reason"] is None


@pytest.mark.parametrize(
    ("llm", "tts", "component"),
    [
        (object(), _AliceQwen(), "llm"),
        (_DeepSeek(), object(), "tts"),
    ],
)
def test_golden_snapshot_rejects_wrong_concrete_provider_type(
    llm: object,
    tts: object,
    component: str,
) -> None:
    config, manager = _seed_pool(llm=llm, tts=tts)

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"][component]["reason"] == "unexpected_provider"


@pytest.mark.parametrize(
    ("llm", "tts", "component"),
    [
        (
            TracingProxy(
                TracingProxy(MockLLM(), service_name="inner"),
                service_name="outer",
            ),
            _AliceQwen(),
            "llm",
        ),
        (
            _DeepSeek(),
            TracingProxy(
                TracingProxy(MockTTS(), service_name="inner"),
                service_name="outer",
            ),
            "tts",
        ),
    ],
)
def test_golden_snapshot_rejects_nested_tracing_mock(
    llm: object,
    tts: object,
    component: str,
) -> None:
    config, manager = _seed_pool(llm=llm, tts=tts)

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"][component]["reason"] == "unexpected_mock"


def test_golden_snapshot_fails_closed_when_preload_status_raises() -> None:
    config, manager = _seed_pool(tts=_BrokenAliceQwen())

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["tts"]["reason"] == "preload_status_unavailable"
    assert "credential" not in json.dumps(payload)


@pytest.mark.parametrize("field", ["ref_audio_path", "ref_text"])
def test_golden_snapshot_rejects_alice_asset_binding_drift(field: str) -> None:
    tts = _AliceQwen()
    setattr(
        tts,
        field,
        (
            "config/personas/voices/not-alice.wav"
            if field == "ref_audio_path"
            else "a different transcript that must never be serialized"
        ),
    )
    config, manager = _seed_pool(tts=tts)

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["tts"]["reason"] == "alice_asset_mismatch"
    serialized = json.dumps(payload)
    assert "not-alice" not in serialized
    assert "different transcript" not in serialized


def test_golden_snapshot_accepts_normalized_equivalent_alice_path() -> None:
    tts = _AliceQwen()
    tts.ref_audio_path = "config/personas/voices/alice_ref.wav"
    config, manager = _seed_pool(tts=tts)
    config.tts.ref_audio_path = "config/personas/voices/../voices/alice_ref.wav"

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is True


def test_golden_snapshot_requires_cached_frontend_assets() -> None:
    config, manager = _seed_pool()

    payload = _snapshot(config=config, manager=manager, frontend_ready=False)

    assert payload["ready"] is False
    assert payload["components"]["frontend"] == {
        "state": "failed",
        "ready": False,
        "required": True,
        "reason": "assets_missing",
    }


def test_golden_snapshot_is_pending_before_pool_initialization() -> None:
    config = _config()
    manager = _manager("unloaded")
    ServicePool._runtime_config = config
    ServicePool._model_manager = manager
    ServicePool._init_state = "pending"

    payload = _snapshot(config=config, manager=manager)

    assert payload["ready"] is False
    assert payload["components"]["pool"] == {
        "state": "pending",
        "ready": False,
        "reason": None,
    }


def test_golden_snapshot_sanitizes_arbitrary_initialization_error() -> None:
    config, manager = _seed_pool()
    ServicePool._init_state = "failed"
    ServicePool._init_error = "https://user:password@example.invalid?api_key=super-secret"

    payload = _snapshot(config=config, manager=manager)

    assert payload["components"]["pool"]["reason"] == "initialization_failed"
    serialized = json.dumps(payload)
    assert "password" not in serialized
    assert "super-secret" not in serialized


def test_development_snapshot_allows_explicit_mocks_but_is_not_acceptance_evidence() -> None:
    config = _config(profile="development")
    config.services.agent = "mock"
    config.services.tts = "mock"
    manager = _manager("unloaded")
    _seed_pool(config=config, llm=MockLLM(), tts=MockTTS(), manager=manager)
    ServicePool._ready = True

    payload = _snapshot(
        config=config,
        manager=manager,
        frontend_ready=False,
    )

    assert payload["ready"] is True
    assert payload["profile"] == "development"
    assert payload["acceptance_eligible"] is False
    assert payload["components"]["frontend"]["required"] is False


def test_development_snapshot_exposes_instrumented_provider_identity() -> None:
    config = _config(profile="development")
    config.services.agent = "deepseek"
    config.services.tts = "mimo"
    llm = InstrumentedServiceProxy(
        _DeepSeek(),
        MagicMock(),
        "llm",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    tts = InstrumentedServiceProxy(
        MockTTS(),
        MagicMock(),
        "tts",
        provider="mimo",
        model="mimo-v2.5-tts",
    )
    manager = _manager("unloaded")
    _seed_pool(config=config, llm=llm, tts=tts, manager=manager)
    ServicePool._ready = True

    payload = _snapshot(config=config, manager=manager, frontend_ready=False)

    assert payload["components"]["llm"] == {
        "state": "ready",
        "ready": True,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "reason": None,
    }
    assert payload["components"]["tts"] == {
        "state": "ready",
        "ready": True,
        "provider": "mimo",
        "model": "mimo-v2.5-tts",
        "reason": None,
    }


async def test_service_context_connectivity_probe_uses_client_and_caches_only_metadata() -> None:
    models = SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=["private-model"])))
    llm = _DeepSeek()
    llm.client = SimpleNamespace(models=models)
    context = ServiceContext()
    context.llm_engine = TracingProxy(
        TracingProxy(llm, service_name="llm-inner"),
        service_name="llm-outer",
    )

    result = await context.verify_llm_connectivity(timeout=0.5)

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert "private-model" not in json.dumps(result)
    assert "super-secret" not in json.dumps(result)
    models.list.assert_awaited_once_with()


async def test_service_context_connectivity_probe_times_out_without_secret_text() -> None:
    blocker = asyncio.Event()

    async def never_returns() -> None:
        await blocker.wait()

    llm = _DeepSeek()
    llm.client = SimpleNamespace(models=SimpleNamespace(list=never_returns))
    context = ServiceContext()
    context.llm_engine = llm

    result = await context.verify_llm_connectivity(timeout=0.01)

    assert result == {
        "state": "failed",
        "ready": False,
        "reason": "timeout",
    }
    assert "super-secret" not in json.dumps(result)


async def test_golden_connectivity_rejects_missing_endpoint_without_probe() -> None:
    llm = _DeepSeek()
    llm.base_url = None
    list_models = AsyncMock()
    llm.client = SimpleNamespace(models=SimpleNamespace(list=list_models))
    context = ServiceContext()
    context.config = _config()
    context.llm_engine = llm

    result = await context.verify_llm_connectivity(timeout=0.5)

    assert result == {
        "state": "failed",
        "ready": False,
        "reason": "endpoint_missing",
    }
    list_models.assert_not_awaited()


async def test_golden_connectivity_rejects_catalog_without_configured_model() -> None:
    llm = _DeepSeek()
    list_models = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(id="deepseek-other-model")])
    )
    llm.client = SimpleNamespace(models=SimpleNamespace(list=list_models))
    context = ServiceContext()
    context.config = _config()
    context.llm_engine = TracingProxy(
        TracingProxy(llm, service_name="inner"),
        service_name="outer",
    )

    result = await context.verify_llm_connectivity(timeout=0.5)

    assert result == {
        "state": "failed",
        "ready": False,
        "reason": "model_unavailable",
    }
    assert "deepseek-other-model" not in json.dumps(result)
    assert "deepseek-other-model" not in json.dumps(context.llm_connectivity_status)


async def test_golden_connectivity_accepts_nested_proxy_and_target_model() -> None:
    llm = _DeepSeek()
    list_models = AsyncMock(
        return_value={
            "data": [
                {"id": "deepseek-v4-flash"},
                {"id": "private-model-that-must-not-be-cached"},
            ]
        }
    )
    llm.client = SimpleNamespace(models=SimpleNamespace(list=list_models))
    context = ServiceContext()
    context.config = _config()
    context.llm_engine = TracingProxy(
        TracingProxy(llm, service_name="inner"),
        service_name="outer",
    )

    result = await context.verify_llm_connectivity(timeout=0.5)

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert "private-model" not in json.dumps(result)
    assert "private-model" not in json.dumps(context.llm_connectivity_status)


async def test_service_context_close_cancels_inflight_connectivity_probe() -> None:
    context = ServiceContext()
    blocker = asyncio.Event()
    task = asyncio.create_task(blocker.wait())
    context._llm_connectivity_task = task

    await context.close()

    assert task.cancelled()
    assert context._llm_connectivity_task is None


async def test_service_context_close_cancels_inflight_model_warmup() -> None:
    context = ServiceContext()
    blocker = asyncio.Event()
    task = asyncio.create_task(blocker.wait())
    context._model_warmup_task = task

    await context.close()

    assert task.cancelled()
    assert context._model_warmup_task is None


async def test_concurrent_model_warmups_run_each_loader_once() -> None:
    manager = ModelLoadingManager()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def loader() -> object:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return object()

    manager.register("tts", loader, "tts")
    first = asyncio.create_task(manager.warmup())
    await entered.wait()
    second = asyncio.create_task(manager.warmup())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    assert calls == 1
    assert manager.get_status() == {"tts": "loaded"}


async def test_golden_pool_awaits_warmup_and_connectivity_before_ready() -> None:
    config = _config()
    llm = _DeepSeek()
    tts = _AliceQwen()
    context = MagicMock()
    context.llm_engine = llm
    context.tts_engine = tts
    context.asr_engine = None
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None
    context.load_from_config = AsyncMock()
    context.wait_for_llm_connectivity = AsyncMock(
        return_value={
            "state": "ready",
            "ready": True,
            "reason": None,
            "latency_ms": 4.2,
        }
    )
    manager = MagicMock()
    manager.warmup = AsyncMock()
    manager.get_status.return_value = {"tts": "loaded"}

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ):
        await ServicePool.init(config, model_manager=manager)

    manager.warmup.assert_awaited_once_with()
    context.wait_for_llm_connectivity.assert_awaited_once_with()
    assert ServicePool.is_ready() is True


async def test_golden_pool_retains_failed_connectivity_as_not_ready() -> None:
    config = _config()
    context = MagicMock()
    context.llm_engine = _DeepSeek()
    context.tts_engine = _AliceQwen()
    context.asr_engine = None
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None
    context.load_from_config = AsyncMock()
    context.wait_for_llm_connectivity = AsyncMock(
        return_value={
            "state": "failed",
            "ready": False,
            "reason": "request_failed",
        }
    )
    manager = MagicMock()
    manager.warmup = AsyncMock()
    manager.get_status.return_value = {"tts": "loaded"}

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ):
        await ServicePool.init(config, model_manager=manager)

    assert ServicePool.is_ready() is False
    payload = _snapshot(config=config, manager=manager)
    assert payload["components"]["llm"]["reason"] == "request_failed"


async def test_repeated_init_does_not_replace_initialized_but_unready_golden_pool() -> None:
    config = _config()
    context = MagicMock()
    context.llm_engine = _DeepSeek()
    context.tts_engine = _AliceQwen()
    context.asr_engine = None
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None
    context.load_from_config = AsyncMock()
    context.wait_for_llm_connectivity = AsyncMock(
        return_value={
            "state": "failed",
            "ready": False,
            "reason": "request_failed",
        }
    )
    manager = MagicMock()
    manager.warmup = AsyncMock()
    manager.get_status.return_value = {"tts": "loaded"}

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ) as context_class:
        await ServicePool.init(config, model_manager=manager)
        first_llm = ServicePool._llm
        await ServicePool.init(config, model_manager=manager)

    context_class.assert_called_once_with(model_manager=manager)
    context.load_from_config.assert_awaited_once_with(config, initialize_memory=False)
    assert ServicePool._llm is first_llm
    assert ServicePool.is_ready() is False


async def test_concurrent_pool_init_shares_one_initialization_task() -> None:
    config = _config(profile="development")
    entered = asyncio.Event()
    release = asyncio.Event()
    context = MagicMock()
    context.llm_engine = MagicMock()
    context.tts_engine = MagicMock()
    context.asr_engine = None
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None

    async def load_from_config(_config: object, *, initialize_memory: bool) -> None:
        assert initialize_memory is False
        entered.set()
        await release.wait()

    context.load_from_config = AsyncMock(side_effect=load_from_config)
    context.llm_connectivity_status = {
        "state": "pending",
        "ready": False,
        "reason": None,
    }

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ) as context_class:
        first = asyncio.create_task(ServicePool.init(config))
        await entered.wait()
        second = asyncio.create_task(ServicePool.init(config))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)

    context_class.assert_called_once_with(model_manager=None)
    context.load_from_config.assert_awaited_once_with(config, initialize_memory=False)


@pytest.mark.parametrize("stage", ["load", "warmup", "connectivity"])
async def test_cancelled_golden_init_cleans_every_partial_stage(stage: str) -> None:
    config = _config()
    entered = asyncio.Event()
    blocker = asyncio.Event()
    llm = MagicMock()
    llm.close = AsyncMock()
    tts = MagicMock()
    tts.close = AsyncMock()
    asr = MagicMock()
    asr.close = AsyncMock()
    context = MagicMock()
    context.llm_engine = llm
    context.tts_engine = tts
    context.asr_engine = asr
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None
    context.close = AsyncMock()

    async def load(_config: object, *, initialize_memory: bool) -> None:
        assert initialize_memory is False
        if stage == "load":
            entered.set()
            await blocker.wait()

    async def warmup() -> None:
        if stage == "warmup":
            entered.set()
            await blocker.wait()

    async def connectivity() -> dict[str, object]:
        if stage == "connectivity":
            entered.set()
            await blocker.wait()
        return {"state": "ready", "ready": True, "reason": None}

    context.load_from_config = AsyncMock(side_effect=load)
    context.wait_for_llm_connectivity = AsyncMock(side_effect=connectivity)
    manager = MagicMock()
    manager.warmup = AsyncMock(side_effect=warmup)
    manager.get_status.return_value = {"tts": "loaded"}

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ):
        init_task = asyncio.create_task(ServicePool.init(config, model_manager=manager))
        await entered.wait()
        init_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await init_task

    context.close.assert_awaited_once_with()
    llm.close.assert_awaited_once_with()
    tts.close.assert_awaited_once_with()
    asr.close.assert_awaited_once_with()
    assert ServicePool._llm is None
    assert ServicePool._tts is None
    assert ServicePool._asr is None
    assert ServicePool._ctx is None
    assert ServicePool._init_state == "failed"
    assert ServicePool._init_error == "initialization_cancelled"
    assert ServicePool._initializing_task is None


async def test_shutdown_waits_for_inflight_init_before_final_cleanup() -> None:
    config = _config(profile="development")
    entered = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()
    llm = MagicMock()
    llm.close = AsyncMock()
    tts = MagicMock()
    tts.close = AsyncMock()
    context = MagicMock()
    context.llm_engine = llm
    context.tts_engine = tts
    context.asr_engine = None
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None
    context.close = AsyncMock()
    context.llm_connectivity_status = {
        "state": "pending",
        "ready": False,
        "reason": None,
    }

    async def cancellation_resistant_load(_config: object, *, initialize_memory: bool) -> None:
        assert initialize_memory is False
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()

    context.load_from_config = AsyncMock(side_effect=cancellation_resistant_load)

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ):
        init_task = asyncio.create_task(ServicePool.init(config))
        await entered.wait()
        shutdown_task = asyncio.create_task(ServicePool.shutdown())
        await cancellation_seen.wait()
        assert shutdown_task.done() is False
        release.set()
        await shutdown_task
        await asyncio.gather(init_task, return_exceptions=True)

    assert ServicePool._llm is None
    assert ServicePool._tts is None
    assert ServicePool._ctx is None
    assert ServicePool._runtime_config is None
    assert ServicePool._model_manager is None
    assert ServicePool._init_state == "closed"
    assert ServicePool._initializing_task is None


async def test_shutdown_marks_every_readiness_signal_nonready_before_await() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    llm = MagicMock()

    async def close() -> None:
        entered.set()
        await release.wait()

    llm.close = AsyncMock(side_effect=close)
    ServicePool._llm = llm
    ServicePool._ready = True
    ServicePool._init_state = "ready"
    ServicePool._llm_connectivity = {
        "state": "ready",
        "ready": True,
        "reason": None,
    }

    shutdown = asyncio.create_task(ServicePool.shutdown())
    await entered.wait()

    observed = (
        ServicePool._ready,
        ServicePool._init_state,
        ServicePool._llm_connectivity["ready"],
    )

    release.set()
    await shutdown
    assert observed == (False, "closing", False)


async def test_concurrent_shutdown_callers_close_each_engine_once() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    llm = MagicMock()

    async def close() -> None:
        entered.set()
        await release.wait()

    llm.close = AsyncMock(side_effect=close)
    ServicePool._llm = llm
    ServicePool._ready = True
    ServicePool._init_state = "ready"

    first = asyncio.create_task(ServicePool.shutdown())
    await entered.wait()
    second = asyncio.create_task(ServicePool.shutdown())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    llm.close.assert_awaited_once_with()
    assert ServicePool._init_state == "closed"


async def test_cancelling_shutdown_waiter_does_not_cancel_shared_cleanup() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    llm = MagicMock()

    async def close() -> None:
        entered.set()
        await release.wait()

    llm.close = AsyncMock(side_effect=close)
    ServicePool._llm = llm
    ServicePool._ready = True
    ServicePool._init_state = "ready"

    waiter = asyncio.create_task(ServicePool.shutdown())
    await entered.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    shared = ServicePool._shutdown_task
    shared_was_running = shared is not None and not shared.done()
    release.set()
    if shared is not None:
        await asyncio.shield(shared)

    assert shared_was_running is True
    llm.close.assert_awaited_once_with()
    assert ServicePool._init_state == "closed"
    assert ServicePool._llm is None


async def test_shutdown_gate_prevents_cancellation_resistant_init_ready_writeback() -> None:
    config = _config(profile="development")
    entered = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release_init = asyncio.Event()
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    llm = MagicMock()

    async def close() -> None:
        close_entered.set()
        await release_close.wait()

    llm.close = AsyncMock(side_effect=close)
    tts = MagicMock()
    tts.close = AsyncMock()
    context = MagicMock()
    context.llm_engine = llm
    context.tts_engine = tts
    context.asr_engine = None
    context.vad_engine = None
    context.memory_system = None
    context.emotion_analyzer = None
    context.audio_processor = None
    context.close = AsyncMock()
    context.llm_connectivity_status = {
        "state": "pending",
        "ready": False,
        "reason": None,
    }

    async def cancellation_resistant_load(_config: object, *, initialize_memory: bool) -> None:
        assert initialize_memory is False
        entered.set()
        try:
            await release_init.wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release_init.wait()

    context.load_from_config = AsyncMock(side_effect=cancellation_resistant_load)

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ):
        init_task = asyncio.create_task(ServicePool.init(config))
        await entered.wait()
        shutdown_task = asyncio.create_task(ServicePool.shutdown())
        await cancellation_seen.wait()
        state_after_cancel = (ServicePool._init_state, ServicePool._ready)

        release_init.set()
        await close_entered.wait()
        state_during_close = (ServicePool._init_state, ServicePool._ready)

        release_close.set()
        await shutdown_task
        await asyncio.gather(init_task, return_exceptions=True)

    assert state_after_cancel == ("closing", False)
    assert state_during_close == ("closing", False)
    assert ServicePool._init_state == "closed"
    assert ServicePool._llm is None
    assert ServicePool._tts is None


async def test_failed_initialization_requires_shutdown_before_retry() -> None:
    config = _config(profile="development")
    context = MagicMock()
    context.llm_engine = None
    context.tts_engine = None
    context.asr_engine = None
    context.close = AsyncMock()
    context.load_from_config = AsyncMock(side_effect=RuntimeError("secret failure"))

    with patch(
        "animetta.runtime.provider_pool.ServiceContext",
        return_value=context,
    ) as context_class:
        with pytest.raises(RuntimeError, match="secret failure"):
            await ServicePool.init(config)
        with pytest.raises(RuntimeError, match="explicit shutdown"):
            await ServicePool.init(config)

    context_class.assert_called_once_with(model_manager=None)
    await ServicePool.shutdown()
    assert ServicePool._init_state == "closed"


def test_golden_get_context_rejects_unready_pool_instead_of_triggering_full_init() -> None:
    config, manager = _seed_pool(
        connectivity={
            "state": "failed",
            "ready": False,
            "reason": "request_failed",
        }
    )
    ServicePool._runtime_config = config
    ServicePool._model_manager = manager

    with pytest.raises(RuntimeError, match="not ready"):
        ServicePool.get_context()


async def test_golden_session_does_not_fallback_to_second_engine_set() -> None:
    from animetta.orchestration.server.session import SessionManager

    config, manager = _seed_pool(
        connectivity={
            "state": "failed",
            "ready": False,
            "reason": "request_failed",
        }
    )
    ServicePool._runtime_config = config
    ServicePool._model_manager = manager
    context = MagicMock()
    context.load_from_config = AsyncMock()

    with patch(
        "animetta.orchestration.server.session.ServiceContext",
        return_value=context,
    ):
        session_manager = SessionManager(model_manager=manager)
        with pytest.raises(RuntimeError, match="not ready"):
            await session_manager.get_or_create_context(
                "sid",
                config,
                AsyncMock(),
            )

    context.load_from_config.assert_not_awaited()
    assert "sid" not in session_manager.contexts


async def test_shutdown_closes_engines_even_when_readiness_never_succeeded() -> None:
    llm = MagicMock()
    llm.close = AsyncMock()
    tts = MagicMock()
    tts.close = AsyncMock()
    ServicePool._llm = llm
    ServicePool._tts = tts
    ServicePool._ready = False
    ServicePool._init_state = "failed"

    await ServicePool.shutdown()

    llm.close.assert_awaited_once_with()
    tts.close.assert_awaited_once_with()
    assert ServicePool._llm is None
    assert ServicePool._tts is None


async def test_shutdown_is_best_effort_and_clears_runtime_references() -> None:
    llm = MagicMock()
    llm.close = AsyncMock(
        side_effect=RuntimeError("https://user:password@example.invalid?key=secret")
    )
    tts = MagicMock()
    tts.close = AsyncMock()
    asr = MagicMock()
    asr.close = AsyncMock()
    ServicePool._llm = llm
    ServicePool._tts = tts
    ServicePool._asr = asr
    ServicePool._runtime_config = _config()
    ServicePool._model_manager = _manager()
    ServicePool._init_state = "ready"

    await ServicePool.shutdown()

    llm.close.assert_awaited_once_with()
    tts.close.assert_awaited_once_with()
    asr.close.assert_awaited_once_with()
    assert ServicePool._llm is None
    assert ServicePool._tts is None
    assert ServicePool._asr is None
    assert ServicePool._runtime_config is None
    assert ServicePool._model_manager is None
    assert ServicePool._init_state == "closed"
    assert ServicePool._shutdown_errors == ("llm:RuntimeError",)
    assert "password" not in repr(ServicePool._shutdown_errors)


async def test_late_registration_after_empty_warmup_is_loaded_by_next_warmup() -> None:
    manager = ModelLoadingManager()
    loader = AsyncMock(return_value=object())

    await manager.warmup()
    manager.register("tts", loader, "tts")
    assert manager.get_status() == {"tts": "unloaded"}

    await manager.warmup()

    loader.assert_awaited_once_with()
    assert manager.get_status() == {"tts": "loaded"}
