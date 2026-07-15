from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from animetta.services.tts.qwen3_tts import (
    Qwen3TTSTTS,
    _resolve_cached_model_source,
    _temporary_qwen_loader_patches,
)


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def _transformers_classes():
    class AutoProcessor:
        @classmethod
        def from_pretrained(cls, *_args, **kwargs):
            return cls, kwargs

        @classmethod
        def register(cls, *args, **kwargs):
            return cls, args, kwargs

    class PreTrainedTokenizerBase:
        @classmethod
        def _patch_mistral_regex(cls, tokenizer, **_kwargs):
            return cls, tokenizer

    return AutoProcessor, PreTrainedTokenizerBase


class _PatchableQwenModule(ModuleType):
    fail_auto_assignment = False

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "AutoProcessor" and self.fail_auto_assignment:
            ModuleType.__setattr__(self, "fail_auto_assignment", False)
            ModuleType.__setattr__(self, name, value)
            raise RuntimeError("qwen module binding assignment fault")
        ModuleType.__setattr__(self, name, value)


def _install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stage: str = "success",
    outcomes: list[object] | None = None,
    block_model: bool = False,
) -> SimpleNamespace:
    auto_processor, tokenizer_base = _transformers_classes()
    original_auto_descriptor = vars(auto_processor)["from_pretrained"]
    original_tokenizer_descriptor = vars(tokenizer_base)["_patch_mistral_regex"]
    descriptor_observations: list[tuple[bool, bool]] = []
    calls: list[dict[str, Any]] = []
    model_sources: list[str] = []
    nested_processor_calls: list[dict[str, Any]] = []
    model_called = threading.Event()
    model_release = threading.Event()
    if not block_model:
        model_release.set()
    remaining_outcomes = list(outcomes or [SimpleNamespace(name="loaded-model")])
    qwen_model_module = _PatchableQwenModule("fake_qwen_tts.modeling")
    qwen_model_module.AutoProcessor = auto_processor

    class FakeQwenModel:
        @classmethod
        def from_pretrained(cls, _model, **kwargs):
            model_sources.append(_model)
            _, processor_kwargs = qwen_model_module.AutoProcessor.from_pretrained(
                "nested-processor",
                fix_mistral_regex=True,
            )
            nested_processor_calls.append(processor_kwargs)
            model_called.set()
            if not model_release.wait(2.0):
                raise TimeoutError("test did not release fake model load")
            calls.append(dict(kwargs))
            descriptor_observations.append(
                (
                    vars(auto_processor)["from_pretrained"]
                    is original_auto_descriptor,
                    vars(tokenizer_base)["_patch_mistral_regex"]
                    is original_tokenizer_descriptor,
                )
            )
            outcome = remaining_outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    FakeQwenModel.__module__ = qwen_model_module.__name__
    qwen_model_module.Qwen3TTSModel = FakeQwenModel
    qwen_model_module.fail_auto_assignment = stage == "module_assignment"

    class FakeOutOfMemoryError(RuntimeError):
        pass

    fake_cuda = SimpleNamespace(
        OutOfMemoryError=FakeOutOfMemoryError,
        is_available=lambda: False,
        is_bf16_supported=lambda: False,
    )
    monkeypatch.setitem(
        sys.modules,
        "torch",
        _module("torch", cuda=fake_cuda, float16=object(), bfloat16=object()),
    )
    monkeypatch.setitem(
        sys.modules,
        "qwen_tts",
        _module("qwen_tts", Qwen3TTSModel=FakeQwenModel),
    )
    monkeypatch.setitem(sys.modules, qwen_model_module.__name__, qwen_model_module)

    transformers = _module("transformers")
    transformers.__path__ = []
    if stage != "transformers_auto_missing":
        transformers.AutoProcessor = auto_processor
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.delitem(sys.modules, "transformers.tokenization_utils_base", raising=False)
    if stage != "tokenizer_module_missing":
        monkeypatch.setitem(
            sys.modules,
            "transformers.tokenization_utils_base",
            _module(
                "transformers.tokenization_utils_base",
                PreTrainedTokenizerBase=tokenizer_base,
            ),
        )

    hf_sentinel = object()
    tf_sentinel = object()
    hf_constants = _module("huggingface_hub.constants", HF_HUB_OFFLINE=hf_sentinel)
    huggingface_hub = _module("huggingface_hub", constants=hf_constants)
    huggingface_hub.__path__ = []
    tf_hub = _module("transformers.utils.hub", _is_offline_mode=tf_sentinel)
    tf_utils = _module("transformers.utils", hub=tf_hub)
    tf_utils.__path__ = []
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", hf_constants)
    monkeypatch.setitem(sys.modules, "transformers.utils", tf_utils)
    monkeypatch.setitem(sys.modules, "transformers.utils.hub", tf_hub)
    monkeypatch.setenv("HF_HUB_OFFLINE", "original-hf-value")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "original-transformers-value")

    return SimpleNamespace(
        auto_processor=auto_processor,
        tokenizer_base=tokenizer_base,
        original_auto_descriptor=original_auto_descriptor,
        original_tokenizer_descriptor=original_tokenizer_descriptor,
        calls=calls,
        model_sources=model_sources,
        nested_processor_calls=nested_processor_calls,
        model_called=model_called,
        model_release=model_release,
        qwen_model_module=qwen_model_module,
        qwen_model_class=FakeQwenModel,
        remaining_outcomes=remaining_outcomes,
        descriptor_observations=descriptor_observations,
        hf_constants=hf_constants,
        hf_sentinel=hf_sentinel,
        tf_hub=tf_hub,
        tf_sentinel=tf_sentinel,
        out_of_memory_error=FakeOutOfMemoryError,
    )


def _assert_process_state_restored(runtime: SimpleNamespace) -> None:
    assert os.environ["HF_HUB_OFFLINE"] == "original-hf-value"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "original-transformers-value"
    assert runtime.hf_constants.HF_HUB_OFFLINE is runtime.hf_sentinel
    assert runtime.tf_hub._is_offline_mode is runtime.tf_sentinel
    assert vars(runtime.auto_processor)["from_pretrained"] is runtime.original_auto_descriptor
    assert (
        vars(runtime.tokenizer_base)["_patch_mistral_regex"]
        is runtime.original_tokenizer_descriptor
    )
    assert runtime.qwen_model_module.AutoProcessor is runtime.auto_processor


def test_qwen_patch_window_does_not_change_external_transformers_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(monkeypatch, block_model=True)
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=False)
    owner_errors: list[BaseException] = []
    outsider_errors: list[BaseException] = []
    outsider_done = threading.Event()
    observations: dict[str, Any] = {}

    def load_qwen() -> None:
        try:
            provider._load_model()
        except BaseException as exc:
            owner_errors.append(exc)

    def call_transformers_directly() -> None:
        try:
            observations["auto_descriptor"] = vars(runtime.auto_processor)[
                "from_pretrained"
            ]
            observations["tokenizer_descriptor"] = vars(runtime.tokenizer_base)[
                "_patch_mistral_regex"
            ]
            observations["processor_result"] = (
                runtime.auto_processor.from_pretrained(
                    "external-processor",
                    fix_mistral_regex=True,
                    external_marker="preserved",
                )
            )
            tokenizer = object()
            observations["tokenizer"] = tokenizer
            observations["tokenizer_result"] = (
                runtime.tokenizer_base._patch_mistral_regex(
                    tokenizer,
                    external_marker="preserved",
                )
            )
            observations["qwen_binding"] = runtime.qwen_model_module.AutoProcessor
        except BaseException as exc:
            outsider_errors.append(exc)
        finally:
            outsider_done.set()

    owner = threading.Thread(target=load_qwen, daemon=True)
    outsider = threading.Thread(target=call_transformers_directly, daemon=True)
    owner.start()
    assert runtime.model_called.wait(2.0)
    outsider.start()

    try:
        assert outsider_done.wait(0.2), "external Transformers call waited on Qwen lock"
    finally:
        runtime.model_release.set()
        owner.join(timeout=2.0)
        outsider.join(timeout=2.0)

    assert not owner.is_alive()
    assert not outsider.is_alive()
    assert owner_errors == []
    assert outsider_errors == []
    assert observations["auto_descriptor"] is runtime.original_auto_descriptor
    assert (
        observations["tokenizer_descriptor"]
        is runtime.original_tokenizer_descriptor
    )
    _, processor_kwargs = observations["processor_result"]
    assert processor_kwargs == {
        "fix_mistral_regex": True,
        "external_marker": "preserved",
    }
    tokenizer_cls, tokenizer = observations["tokenizer_result"]
    assert tokenizer_cls is runtime.tokenizer_base
    assert tokenizer is observations["tokenizer"]
    assert observations["qwen_binding"] is not runtime.auto_processor
    assert runtime.nested_processor_calls == [
        {"fix_mistral_regex": False, "local_files_only": True}
    ]
    _assert_process_state_restored(runtime)


def test_loader_success_is_local_only_and_restores_process_state(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(monkeypatch)
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=False)

    provider._load_model()

    assert provider._loaded is True
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["device_map"] == "cpu"
    assert runtime.calls[0]["local_files_only"] is True
    assert set(runtime.calls[0]) == {"device_map", "dtype", "local_files_only"}
    assert runtime.nested_processor_calls == [
        {"fix_mistral_regex": False, "local_files_only": True}
    ]
    assert runtime.descriptor_observations == [(True, True)]
    _assert_process_state_restored(runtime)


def test_loader_passes_active_local_snapshot_to_qwen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _install_fake_runtime(monkeypatch)
    revision = "0123456789abcdef"
    snapshot = (
        tmp_path
        / "hub"
        / "models--Qwen--Qwen3-TTS-12Hz-0.6B-Base"
        / "snapshots"
        / revision
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    refs = snapshot.parents[1] / "refs"
    refs.mkdir()
    (refs / "main").write_text(revision, encoding="utf-8")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    provider = Qwen3TTSTTS(
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device="cpu",
        dtype="float16",
        use_flash_attn=False,
    )

    provider._load_model()

    assert _resolve_cached_model_source(provider.model) == str(snapshot.resolve())
    assert runtime.model_sources == [str(snapshot.resolve())]


def test_loader_uses_explicit_pinned_revision_instead_of_active_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _install_fake_runtime(monkeypatch)
    model_root = tmp_path / "hub" / "models--Qwen--Qwen3-TTS-12Hz-0.6B-Base"
    pinned_revision = "pinned0123456789"
    active_revision = "active9876543210"
    for revision in (pinned_revision, active_revision):
        snapshot = model_root / "snapshots" / revision
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
    refs = model_root / "refs"
    refs.mkdir()
    (refs / "main").write_text(active_revision, encoding="utf-8")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    provider = Qwen3TTSTTS(
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        revision=pinned_revision,
        device="cpu",
        dtype="float16",
        use_flash_attn=False,
    )

    provider._load_model()

    expected = str((model_root / "snapshots" / pinned_revision).resolve())
    assert _resolve_cached_model_source(provider.model, pinned_revision) == expected
    assert runtime.model_sources == [expected]


def test_loader_fails_closed_when_pinned_revision_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    provider = Qwen3TTSTTS(
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        revision="missing-revision",
        device="cpu",
        dtype="float16",
        use_flash_attn=False,
    )

    with pytest.raises(FileNotFoundError, match="Pinned Qwen model revision is unavailable"):
        provider._load_model()


@pytest.mark.parametrize(
    "stage",
    [
        "module_assignment",
        "model_load",
    ],
)
def test_loader_faults_restore_qwen_module_binding(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
):
    outcomes = [RuntimeError("model load fault")] if stage == "model_load" else None
    runtime = _install_fake_runtime(monkeypatch, stage=stage, outcomes=outcomes)
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=False)

    with pytest.raises((ImportError, RuntimeError)):
        provider._load_model()

    _assert_process_state_restored(runtime)


@pytest.mark.parametrize(
    "stage",
    ["transformers_auto_missing", "tokenizer_module_missing"],
)
def test_loader_does_not_depend_on_global_transformers_patch_targets(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
):
    runtime = _install_fake_runtime(monkeypatch, stage=stage)
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=False)

    provider._load_model()

    assert provider._loaded is True
    assert runtime.nested_processor_calls == [
        {"fix_mistral_regex": False, "local_files_only": True}
    ]
    if stage == "transformers_auto_missing":
        assert not hasattr(sys.modules["transformers"], "AutoProcessor")
    else:
        assert "transformers.tokenization_utils_base" not in sys.modules
    _assert_process_state_restored(runtime)


def test_flash_attention_retry_stays_local_only_and_restores_descriptors(
    monkeypatch: pytest.MonkeyPatch,
):
    loaded_model = SimpleNamespace(name="fallback-model")
    runtime = _install_fake_runtime(
        monkeypatch,
        outcomes=[RuntimeError("flash_attn unavailable"), loaded_model],
    )
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=True)

    provider._load_model()

    assert provider._model is loaded_model
    assert len(runtime.calls) == 2
    assert runtime.calls[0]["local_files_only"] is True
    assert runtime.calls[0]["attn_implementation"] == "flash_attention_2"
    assert runtime.calls[1]["local_files_only"] is True
    assert "attn_implementation" not in runtime.calls[1]
    assert runtime.descriptor_observations == [(True, True), (True, True)]
    _assert_process_state_restored(runtime)


def test_temporary_qwen_module_facade_is_local_only_and_preserves_register(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(monkeypatch)

    with _temporary_qwen_loader_patches(runtime.qwen_model_class):
        facade = runtime.qwen_model_module.AutoProcessor
        _, processor_kwargs = facade.from_pretrained(
            "nested-processor",
            fix_mistral_regex=True,
        )
        registered_cls, args, kwargs = facade.register("kind", value="handler")

    assert processor_kwargs["local_files_only"] is True
    assert processor_kwargs["fix_mistral_regex"] is False
    assert registered_cls is runtime.auto_processor
    assert args == ("kind",)
    assert kwargs == {"value": "handler"}
    _assert_process_state_restored(runtime)


def test_qwen_module_facade_overrides_online_processor_request(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(monkeypatch)

    with _temporary_qwen_loader_patches(runtime.qwen_model_class):
        _, processor_kwargs = (
            runtime.qwen_model_module.AutoProcessor.from_pretrained(
                "nested-processor",
                fix_mistral_regex=True,
                local_files_only=False,
            )
        )

    assert processor_kwargs == {
        "fix_mistral_regex": False,
        "local_files_only": True,
    }
    _assert_process_state_restored(runtime)


def test_flash_attention_fallback_failure_still_restores_process_state(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(
        monkeypatch,
        outcomes=[
            RuntimeError("flash_attn unavailable"),
            RuntimeError("fallback model failure"),
        ],
    )
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=True)

    with pytest.raises(RuntimeError, match="fallback model failure"):
        provider._load_model()

    assert len(runtime.calls) == 2
    assert all(call["local_files_only"] is True for call in runtime.calls)
    _assert_process_state_restored(runtime)


def test_out_of_memory_does_not_retry_as_flash_attention_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(monkeypatch)
    runtime.remaining_outcomes[:] = [runtime.out_of_memory_error("gpu exhausted")]
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=True)

    with pytest.raises(RuntimeError, match="GPU out of memory"):
        provider._load_model()

    assert len(runtime.calls) == 1
    _assert_process_state_restored(runtime)


def test_non_flash_model_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _install_fake_runtime(
        monkeypatch,
        outcomes=[RuntimeError("unrelated model failure")],
    )
    provider = Qwen3TTSTTS(device="cpu", dtype="float16", use_flash_attn=True)

    with pytest.raises(RuntimeError, match="unrelated model failure"):
        provider._load_model()

    assert len(runtime.calls) == 1
    _assert_process_state_restored(runtime)


def test_uncached_darwin_model_preserves_online_compatibility_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    runtime = _install_fake_runtime(monkeypatch)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    provider = Qwen3TTSTTS(
        model="compat/Darwin-TTS",
        device="cpu",
        dtype="float16",
        use_flash_attn=True,
    )

    provider._load_model()

    assert provider._loaded is True
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["device_map"] == "cpu"
    assert "local_files_only" not in runtime.calls[0]
    assert "attn_implementation" not in runtime.calls[0]
    _assert_process_state_restored(runtime)


def test_darwin_load_waits_for_temporary_patch_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    runtime = _install_fake_runtime(monkeypatch)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    provider = Qwen3TTSTTS(
        model="compat/Darwin-TTS",
        device="cpu",
        dtype="float16",
    )
    patch_entered = threading.Event()
    patch_release = threading.Event()
    thread_errors: list[BaseException] = []

    def hold_patch_window() -> None:
        try:
            with _temporary_qwen_loader_patches(runtime.qwen_model_class):
                patch_entered.set()
                assert patch_release.wait(2.0), "test did not release patch window"
        except BaseException as exc:
            thread_errors.append(exc)

    def load_darwin() -> None:
        try:
            provider._load_model()
        except BaseException as exc:
            thread_errors.append(exc)

    patch_thread = threading.Thread(target=hold_patch_window, daemon=True)
    load_thread = threading.Thread(target=load_darwin, daemon=True)
    patch_thread.start()
    assert patch_entered.wait(2.0)
    load_thread.start()

    assert not runtime.model_called.wait(0.1)
    patch_release.set()
    patch_thread.join(timeout=2.0)
    load_thread.join(timeout=2.0)

    assert not patch_thread.is_alive()
    assert not load_thread.is_alive()
    assert thread_errors == []
    assert runtime.model_called.is_set()
    _assert_process_state_restored(runtime)
