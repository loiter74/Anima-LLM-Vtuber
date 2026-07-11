from __future__ import annotations

import json
import shutil
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from animetta.core.golden_preflight import (
    GOLDEN_QWEN_MODEL_ID,
    GoldenPreflightContext,
    run_golden_preflight,
)
from animetta.services.llm.openai_llm import OpenAILLM
from animetta.services.tts.qwen3_tts import Qwen3TTSTTS
from animetta.tracing.proxy import TracingProxy


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 240)


def _write_safetensors(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps(
        {
            "weight": {
                "dtype": "U8",
                "shape": [1],
                "data_offsets": [0, 1],
            }
        }
    ).encode("utf-8")
    path.write_bytes(len(header).to_bytes(8, "little") + header + b"\x00")


def _write_complete_qwen_snapshot(snapshot: Path) -> None:
    json_files = {
        "config.json": {"model_type": "qwen3_tts", "architectures": ["Qwen3TTS"]},
        "generation_config.json": {"eos_token_id": 1},
        "preprocessor_config.json": {"feature_size": 128},
        "tokenizer_config.json": {"tokenizer_class": "Qwen2Tokenizer"},
        "vocab.json": {"token": 0},
        "speech_tokenizer/config.json": {"model_type": "qwen3_tts_tokenizer"},
        "speech_tokenizer/configuration.json": {"sample_rate": 24_000},
        "speech_tokenizer/preprocessor_config.json": {"sampling_rate": 24_000},
    }
    for relative_path, payload in json_files.items():
        path = snapshot / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    (snapshot / "merges.txt").write_text("#version: 0.2\na b\n", encoding="utf-8")
    _write_safetensors(snapshot / "model.safetensors")
    _write_safetensors(snapshot / "speech_tokenizer" / "model.safetensors")


def _write_live2d_model(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "Version": 3,
                "FileReferences": {
                    "Moc": "model.moc3",
                    "Textures": ["textures/texture_00.png"],
                },
            }
        ),
        encoding="utf-8",
    )
    (path.parent / "model.moc3").write_bytes(b"moc")
    texture = path.parent / "textures" / "texture_00.png"
    texture.parent.mkdir(exist_ok=True)
    texture.write_bytes(b"png")


def _golden_config(ref_audio_path: str) -> SimpleNamespace:
    llm = SimpleNamespace(
        type="deepseek",
        model="deepseek-v4-flash",
        thinking="disabled",
        api_key="sk-config-super-secret",
        base_url="https://api.deepseek.com/v1",
    )
    return SimpleNamespace(
        persona="anima.v0.1",
        services=SimpleNamespace(agent="deepseek", tts="alice_vc", local_llm=None),
        system=SimpleNamespace(
            runtime_profile="golden",
            long_term_memory_mode="off",
            enable_tools=False,
            enable_subtitle_translation=False,
            enable_active_memes=False,
        ),
        humor=SimpleNamespace(enabled=False),
        agent=SimpleNamespace(llm_config=llm),
        tts=SimpleNamespace(
            type="qwen3",
            model=GOLDEN_QWEN_MODEL_ID,
            speaker="custom",
            ref_audio_path=ref_audio_path,
            ref_text="Alice reference transcript",
            x_vector_only=False,
        ),
    )


def _real_llm(**overrides: Any) -> OpenAILLM:
    engine = object.__new__(OpenAILLM)
    engine.api_key = "sk-runtime-super-secret"
    engine.model = "deepseek-v4-flash"
    engine.base_url = "https://api.deepseek.com/v1"
    engine.extra_body = {"thinking": {"type": "disabled"}}
    for name, value in overrides.items():
        setattr(engine, name, value)
    return engine


def _real_tts(**overrides: Any) -> Qwen3TTSTTS:
    engine = object.__new__(Qwen3TTSTTS)
    engine.model = GOLDEN_QWEN_MODEL_ID
    engine.speaker = "custom"
    engine.ref_audio_path = "config/personas/voices/alice_ref.wav"
    engine.ref_text = "Alice reference transcript"
    engine.x_vector_only = False
    for name, value in overrides.items():
        setattr(engine, name, value)
    return engine


def _valid_runtime_engines(*, proxied: bool = False) -> dict[str, object]:
    llm: object = _real_llm()
    tts: object = _real_tts()
    if proxied:
        llm = TracingProxy(llm, service_name="llm")
        tts = TracingProxy(tts, service_name="tts")
    return {"llm": llm, "tts": tts}


@pytest.fixture
def golden_environment(tmp_path: Path) -> tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]]:
    ref_audio = tmp_path / "config" / "personas" / "voices" / "alice_ref.wav"
    _write_wav(ref_audio)

    live2d = (
        tmp_path
        / "frontend"
        / "public"
        / "live2d"
        / "haru"
        / "haru_greeter_t03.model3.json"
    )
    live2d.parent.mkdir(parents=True, exist_ok=True)
    live2d.write_text(
        json.dumps(
            {
                "Version": 3,
                "FileReferences": {
                    "Moc": "haru.moc3",
                    "Textures": ["textures/texture_00.png"],
                },
            }
        ),
        encoding="utf-8",
    )
    (live2d.parent / "haru.moc3").write_bytes(b"moc")
    texture = live2d.parent / "textures" / "texture_00.png"
    texture.parent.mkdir()
    texture.write_bytes(b"png")

    frontend_index = tmp_path / "frontend" / "dist" / "index.html"
    frontend_index.parent.mkdir(parents=True, exist_ok=True)
    frontend_index.write_text("<!doctype html>", encoding="utf-8")

    hf_home = tmp_path / "hf"
    revision = "0123456789abcdef"
    snapshot = (
        hf_home
        / "hub"
        / "models--Qwen--Qwen3-TTS-12Hz-0.6B-Base"
        / "snapshots"
        / revision
    )
    snapshot.mkdir(parents=True)
    _write_complete_qwen_snapshot(snapshot)
    refs_main = snapshot.parent.parent / "refs" / "main"
    refs_main.parent.mkdir()
    refs_main.write_text(revision, encoding="utf-8")

    config = _golden_config("config/personas/voices/alice_ref.wav")
    context = GoldenPreflightContext(
        project_root=tmp_path,
        env={
            "DEEPSEEK_API_KEY": "sk-env-super-secret",
            "HF_HOME": str(hf_home),
        },
        cuda_probe=lambda: {
            "available": True,
            "device_count": 1,
            "device_name": "Test CUDA GPU",
        },
        dependency_probe=lambda name: {
            "available": name == "qwen_tts",
            "version": "0.test",
        },
        live2d_model_path="/live2d/haru/haru_greeter_t03.model3.json",
        runtime_engines=_valid_runtime_engines(),
    )
    paths = {
        "ref_audio": ref_audio,
        "live2d": live2d,
        "frontend_index": frontend_index,
        "hf_home": hf_home,
        "snapshot": snapshot,
        "refs_main": refs_main,
    }
    return config, context, paths


def _checks(report: Any) -> dict[str, Any]:
    return {check.name: check for check in report.checks}


def test_missing_credentials_fails_without_short_circuiting(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    config.agent.llm_config.api_key = ""
    context = replace(context, env={"HF_HOME": context.env["HF_HOME"]})

    report = run_golden_preflight(config, context)
    checks = _checks(report)

    assert report.ok is False
    assert checks["credentials"].ok is False
    assert checks["credentials"].code == "missing_credentials"
    assert len(checks) == 22
    assert checks["frontend_dist"].ok is True


def test_enabled_deepseek_thinking_fails_policy_check(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    config.agent.llm_config.thinking = "enabled"

    report = run_golden_preflight(config, context)

    check = _checks(report)["llm_thinking"]
    assert report.ok is False
    assert check.ok is False
    assert check.code == "thinking_enabled"


def test_missing_cuda_fails_with_safe_evidence(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    context = replace(
        context,
        cuda_probe=lambda: {"available": False, "reason": "driver unavailable"},
    )

    report = run_golden_preflight(config, context)

    check = _checks(report)["cuda"]
    assert report.ok is False
    assert check.code == "cuda_unavailable"
    assert check.detail == {"reason": "driver unavailable"}


def test_missing_qwen_dependency_fails(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    context = replace(
        context,
        dependency_probe=lambda _name: {"available": False},
    )

    report = run_golden_preflight(config, context)

    assert _checks(report)["qwen_tts_dependency"].code == "qwen_tts_missing"


def test_missing_model_cache_revision_fails(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    shutil.rmtree(paths["snapshot"])

    report = run_golden_preflight(config, context)

    check = _checks(report)["qwen_model_cache"]
    assert report.ok is False
    assert check.code == "model_cache_active_snapshot_missing"
    assert check.detail["model_id"] == GOLDEN_QWEN_MODEL_ID


@pytest.mark.parametrize("wav_state", ["missing", "empty", "invalid"])
def test_missing_empty_or_invalid_alice_wav_fails(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    wav_state: str,
) -> None:
    config, context, paths = golden_environment
    if wav_state == "missing":
        paths["ref_audio"].unlink()
    elif wav_state == "empty":
        paths["ref_audio"].write_bytes(b"")
    else:
        paths["ref_audio"].write_bytes(b"not a wav")

    report = run_golden_preflight(config, context)

    check = _checks(report)["alice_reference_audio"]
    assert report.ok is False
    assert check.ok is False
    assert check.code == f"reference_audio_{wav_state}"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("ref_text", "   ", "reference_transcript_missing"),
        ("x_vector_only", True, "alice_icl_disabled"),
    ],
)
def test_invalid_alice_icl_configuration_fails(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    field: str,
    value: Any,
    code: str,
) -> None:
    config, context, _ = golden_environment
    setattr(config.tts, field, value)

    report = run_golden_preflight(config, context)

    check = _checks(report)["alice_icl"]
    assert report.ok is False
    assert check.code == code


@pytest.mark.parametrize("missing_asset", ["live2d", "frontend_index"])
def test_missing_live2d_or_frontend_asset_fails(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    missing_asset: str,
) -> None:
    config, context, paths = golden_environment
    paths[missing_asset].unlink()

    report = run_golden_preflight(config, context)

    check_name = "live2d_asset" if missing_asset == "live2d" else "frontend_dist"
    expected_code = "live2d_asset_missing" if missing_asset == "live2d" else "frontend_dist_missing"
    assert report.ok is False
    assert _checks(report)[check_name].code == expected_code


def test_unexpected_mock_runtime_engines_fail(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    mock_llm = type("MockLLM", (), {})()
    mock_tts = type("MockTTS", (), {})()
    context = replace(
        context,
        runtime_engines={"llm": mock_llm, "tts": mock_tts},
    )

    report = run_golden_preflight(config, context)

    check = _checks(report)["runtime_engines"]
    assert report.ok is False
    assert check.code == "mock_engines_detected"
    assert check.detail == {"unexpected": ["llm:MockLLM", "tts:MockTTS"]}


@pytest.mark.parametrize(
    ("path", "value", "check_name", "code"),
    [
        ("services.local_llm", "ollama", "aux_local_llm", "local_llm_enabled"),
        (
            "system.long_term_memory_mode",
            "read_only",
            "aux_long_term_memory",
            "long_term_memory_enabled",
        ),
        ("system.enable_tools", True, "aux_tools", "tools_enabled"),
        (
            "system.enable_subtitle_translation",
            True,
            "aux_subtitle_translation",
            "subtitle_translation_enabled",
        ),
        (
            "system.enable_active_memes",
            True,
            "aux_active_memes",
            "active_memes_enabled",
        ),
        ("humor.enabled", True, "aux_humor", "humor_enabled"),
    ],
)
def test_golden_auxiliary_paths_must_remain_disabled(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    path: str,
    value: Any,
    check_name: str,
    code: str,
) -> None:
    config, context, _ = golden_environment
    target: Any = config
    parts = path.split(".")
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert _checks(report)[check_name].code == code


def test_default_runtime_scope_fails_closed_without_engines(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    context = replace(context, runtime_engines=None)

    report = run_golden_preflight(config, context)

    assert report.scope == "runtime"
    assert report.ok is False
    assert report.acceptance_ready is False
    assert _checks(report)["runtime_engines"].code == "runtime_engines_missing"


def test_static_scope_allows_absent_engines_but_is_never_acceptance_ready(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    context = replace(context, scope="static", runtime_engines=None)

    report = run_golden_preflight(config, context)

    assert report.scope == "static"
    assert report.ok is True
    assert report.acceptance_ready is False
    assert _checks(report)["runtime_engines"].code == "not_required_for_static_scope"


def test_invalid_preflight_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="scope"):
        GoldenPreflightContext(scope="acceptance")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("engines", "code", "missing"),
    [
        ({}, "runtime_engines_missing", ["llm", "tts"]),
        ({"tts": _real_tts()}, "runtime_llm_missing", ["llm"]),
        ({"llm": _real_llm()}, "runtime_tts_missing", ["tts"]),
    ],
)
def test_runtime_scope_rejects_absent_engine_roles(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    engines: dict[str, object],
    code: str,
    missing: list[str],
) -> None:
    config, context, _ = golden_environment
    context = replace(context, runtime_engines=engines)

    report = run_golden_preflight(config, context)

    check = _checks(report)["runtime_engines"]
    assert report.acceptance_ready is False
    assert check.code == code
    assert check.detail["missing"] == missing


@pytest.mark.parametrize(
    ("engines_factory", "issue_code"),
    [
        (lambda: {"llm": object(), "tts": _real_tts()}, "runtime_llm_type_mismatch"),
        (
            lambda: {
                "llm": _real_llm(base_url="https://api.openai.com/v1"),
                "tts": _real_tts(),
            },
            "runtime_llm_provider_mismatch",
        ),
        (
            lambda: {"llm": _real_llm(model="deepseek-v4-pro"), "tts": _real_tts()},
            "runtime_llm_model_mismatch",
        ),
        (
            lambda: {
                "llm": _real_llm(extra_body={"thinking": {"type": "enabled"}}),
                "tts": _real_tts(),
            },
            "runtime_llm_thinking_mismatch",
        ),
        (
            lambda: {"llm": _real_llm(api_key=""), "tts": _real_tts()},
            "runtime_llm_credentials_missing",
        ),
        (lambda: {"llm": _real_llm(), "tts": object()}, "runtime_tts_type_mismatch"),
        (
            lambda: {
                "llm": _real_llm(),
                "tts": _real_tts(model="/snapshot/path"),
            },
            "runtime_tts_model_mismatch",
        ),
        (
            lambda: {"llm": _real_llm(), "tts": _real_tts(speaker="Vivian")},
            "runtime_tts_speaker_mismatch",
        ),
        (
            lambda: {
                "llm": _real_llm(),
                "tts": _real_tts(x_vector_only=True),
            },
            "runtime_tts_icl_mismatch",
        ),
        (
            lambda: {"llm": _real_llm(), "tts": _real_tts(ref_text="")},
            "runtime_tts_icl_mismatch",
        ),
        (
            lambda: {
                "llm": _real_llm(),
                "tts": _real_tts(ref_text="Different reference transcript"),
            },
            "runtime_tts_icl_mismatch",
        ),
        (
            lambda: {
                "llm": _real_llm(),
                "tts": _real_tts(ref_audio_path="other.wav"),
            },
            "runtime_tts_icl_mismatch",
        ),
    ],
)
def test_runtime_scope_rejects_wrong_engine_identity(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    engines_factory: Any,
    issue_code: str,
) -> None:
    config, context, _ = golden_environment
    context = replace(context, runtime_engines=engines_factory())

    report = run_golden_preflight(config, context)

    check = _checks(report)["runtime_engines"]
    assert report.acceptance_ready is False
    assert issue_code in [issue["code"] for issue in check.detail["issues"]]


def test_runtime_scope_unwraps_tracing_proxies_and_accepts_real_engines(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    context = replace(context, runtime_engines=_valid_runtime_engines(proxied=True))

    report = run_golden_preflight(config, context)

    check = _checks(report)["runtime_engines"]
    assert report.scope == "runtime"
    assert report.ok is True
    assert report.acceptance_ready is True
    assert check.code == "ok"
    assert check.detail["proxied"] == ["llm", "tts"]


@pytest.mark.parametrize(
    ("cache_state", "code"),
    [
        ("missing_config", "model_cache_required_file_missing"),
        ("invalid_config", "model_cache_json_invalid"),
        ("missing_weights", "model_cache_required_file_missing"),
        ("empty_weights", "model_cache_safetensors_invalid"),
    ],
)
def test_partial_qwen_snapshot_never_counts_as_cached(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    cache_state: str,
    code: str,
) -> None:
    config, context, paths = golden_environment
    config_path = paths["snapshot"] / "config.json"
    weights_path = paths["snapshot"] / "model.safetensors"
    if cache_state == "missing_config":
        config_path.unlink()
    elif cache_state == "invalid_config":
        config_path.write_text("not json", encoding="utf-8")
    elif cache_state == "missing_weights":
        weights_path.unlink()
    else:
        weights_path.write_bytes(b"")

    report = run_golden_preflight(config, context)

    check = _checks(report)["qwen_model_cache"]
    assert report.ok is False
    assert check.code == code


def test_invalid_live2d_model_manifest_fails(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    paths["live2d"].write_text("not json", encoding="utf-8")

    report = run_golden_preflight(config, context)

    assert _checks(report)["live2d_asset"].code == "live2d_manifest_invalid"


def test_live2d_asset_is_validated_from_deployed_vite_dist(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    deployed_haru = context.project_root / "frontend" / "dist" / "live2d" / "haru"
    deployed_haru.parent.mkdir(parents=True, exist_ok=True)
    paths["live2d"].parent.rename(deployed_haru)

    report = run_golden_preflight(config, context)

    assert _checks(report)["live2d_asset"].ok is True


@pytest.mark.parametrize("missing_reference", ["moc", "texture"])
def test_partial_live2d_asset_fails_when_referenced_file_is_missing(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    missing_reference: str,
) -> None:
    config, context, paths = golden_environment
    model_dir = paths["live2d"].parent
    target = (
        model_dir / "haru.moc3"
        if missing_reference == "moc"
        else model_dir / "textures" / "texture_00.png"
    )
    target.unlink()

    report = run_golden_preflight(config, context)

    check = _checks(report)["live2d_asset"]
    assert report.ok is False
    assert check.code == "live2d_reference_missing"
    assert any(missing_reference in item["kind"] for item in check.detail["missing"])


@pytest.mark.parametrize("yaml_payload", ["model: [", "- not-a-mapping\n"])
def test_malformed_or_non_mapping_live2d_yaml_is_a_complete_failed_report(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    yaml_payload: str,
) -> None:
    config, context, _ = golden_environment
    live2d_config = context.project_root / "config" / "features" / "live2d.yaml"
    live2d_config.parent.mkdir(parents=True, exist_ok=True)
    live2d_config.write_text(yaml_payload, encoding="utf-8")
    context = replace(context, live2d_model_path=None)

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert len(report.checks) == 22
    assert _checks(report)["live2d_asset"].code == "live2d_config_invalid"
    assert _checks(report)["frontend_dist"].ok is True


def test_frontend_permission_error_becomes_a_failed_check_and_does_not_escape(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, context, paths = golden_environment
    frontend_index = paths["frontend_index"]
    original_is_file = Path.is_file
    original_stat = Path.stat

    def guarded_is_file(path: Path) -> bool:
        if path == frontend_index:
            return True
        return original_is_file(path)

    def guarded_stat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == frontend_index:
            raise PermissionError("permission denied")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    monkeypatch.setattr(Path, "stat", guarded_stat)

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert len(report.checks) == 22
    assert _checks(report)["frontend_dist"].code == "frontend_dist_unreadable"
    assert _checks(report)["runtime_engines"].ok is True


def test_runtime_diagnostics_never_expose_url_credentials_query_or_fragment(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    unsafe_url = (
        "https://url-user:url-password@evil.example/v1/private"
        "?access_token=arbitrary-query-token#arbitrary-fragment"
    )
    context = replace(
        context,
        runtime_engines={"llm": _real_llm(base_url=unsafe_url), "tts": _real_tts()},
    )

    payload = run_golden_preflight(config, context).to_json()

    assert "url-user" not in payload
    assert "url-password" not in payload
    assert "arbitrary-query-token" not in payload
    assert "arbitrary-fragment" not in payload
    assert "https://evil.example/v1/private" in payload


def test_composite_sensitive_keys_and_arbitrary_assignments_are_redacted(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    secrets = {
        "client_secret_value": "opaque-client-secret-value",
        "authorization_header": "Basic opaque-authorization-value",
        "password_reset_token": "opaque-reset-token",
        "reason": (
            "password=arbitrary-password "
            "client_secret=arbitrary-client-secret "
            "access_token=arbitrary-access-token"
        ),
    }
    context = replace(
        context,
        cuda_probe=lambda: {"available": False, **secrets},
    )

    payload = run_golden_preflight(config, context).to_json()

    for secret in (
        "opaque-client-secret-value",
        "opaque-authorization-value",
        "opaque-reset-token",
        "arbitrary-password",
        "arbitrary-client-secret",
        "arbitrary-access-token",
    ):
        assert secret not in payload
    assert payload.count("<redacted>") >= 4


@pytest.mark.parametrize(
    "relative_path",
    [
        "config.json",
        "generation_config.json",
        "merges.txt",
        "model.safetensors",
        "preprocessor_config.json",
        "tokenizer_config.json",
        "vocab.json",
        "speech_tokenizer/config.json",
        "speech_tokenizer/configuration.json",
        "speech_tokenizer/model.safetensors",
        "speech_tokenizer/preprocessor_config.json",
    ],
)
def test_active_qwen_snapshot_requires_every_fixed_companion(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    relative_path: str,
) -> None:
    config, context, paths = golden_environment
    (paths["snapshot"] / relative_path).unlink()

    report = run_golden_preflight(config, context)

    check = _checks(report)["qwen_model_cache"]
    assert report.ok is False
    assert check.code == "model_cache_required_file_missing"
    assert relative_path in check.detail["missing"]


def test_active_qwen_ref_is_required(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    paths["refs_main"].unlink()

    report = run_golden_preflight(config, context)

    assert _checks(report)["qwen_model_cache"].code == "model_cache_ref_missing"


def test_broken_active_qwen_ref_never_falls_back_to_another_snapshot(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    paths["refs_main"].write_text("missing-revision", encoding="utf-8")

    report = run_golden_preflight(config, context)

    check = _checks(report)["qwen_model_cache"]
    assert check.code == "model_cache_active_snapshot_missing"
    assert check.detail["revision"] == "missing-revision"


def test_partial_active_snapshot_never_falls_back_to_old_complete_snapshot(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    active_revision = "active-partial-revision"
    active_snapshot = paths["snapshot"].parent / active_revision
    _write_complete_qwen_snapshot(active_snapshot)
    (active_snapshot / "generation_config.json").unlink()
    paths["refs_main"].write_text(active_revision, encoding="utf-8")

    report = run_golden_preflight(config, context)

    check = _checks(report)["qwen_model_cache"]
    assert report.ok is False
    assert check.code == "model_cache_required_file_missing"
    assert check.detail["revision"] == active_revision


def test_fake_json_and_one_byte_safetensors_do_not_count_as_cached(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    (paths["snapshot"] / "config.json").write_text("{}", encoding="utf-8")
    (paths["snapshot"] / "model.safetensors").write_bytes(b"x")

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert _checks(report)["qwen_model_cache"].code in {
        "model_cache_json_invalid",
        "model_cache_safetensors_invalid",
    }


def test_one_byte_safetensors_with_valid_json_is_rejected(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    (paths["snapshot"] / "model.safetensors").write_bytes(b"x")

    report = run_golden_preflight(config, context)

    assert _checks(report)["qwen_model_cache"].code == "model_cache_safetensors_invalid"


def test_overlapping_safetensors_offsets_are_rejected(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    header = json.dumps(
        {
            "first": {"dtype": "U8", "shape": [1], "data_offsets": [0, 1]},
            "second": {"dtype": "U8", "shape": [1], "data_offsets": [0, 1]},
        }
    ).encode("utf-8")
    (paths["snapshot"] / "model.safetensors").write_bytes(
        len(header).to_bytes(8, "little") + header + b"\x00"
    )

    report = run_golden_preflight(config, context)

    assert _checks(report)["qwen_model_cache"].code == "model_cache_safetensors_invalid"


def test_shard_index_must_resolve_every_weight_map_entry(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    index = paths["snapshot"] / "model.safetensors.index.json"
    index.write_text(
        json.dumps(
            {
                "weight_map": {
                    "a": "model-00001-of-00002.safetensors",
                    "b": "model-00002-of-00002.safetensors",
                }
            }
        ),
        encoding="utf-8",
    )
    _write_safetensors(paths["snapshot"] / "model-00001-of-00002.safetensors")

    report = run_golden_preflight(config, context)

    check = _checks(report)["qwen_model_cache"]
    assert report.ok is False
    assert check.code == "model_cache_shard_missing"
    assert check.detail["missing_shards"] == ["model-00002-of-00002.safetensors"]


def test_malformed_shard_index_is_a_failed_check_not_an_exception(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, paths = golden_environment
    index = paths["snapshot"] / "model.safetensors.index.json"
    index.write_text(
        json.dumps({"weight_map": {"a": ["not", "a", "path"]}}),
        encoding="utf-8",
    )

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert len(report.checks) == 22
    assert _checks(report)["qwen_model_cache"].code == "model_cache_shard_index_invalid"


@pytest.mark.parametrize("path_kind", ["web_traversal", "absolute_external"])
def test_live2d_manifest_must_remain_under_public_live2d_root(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    path_kind: str,
) -> None:
    config, context, _ = golden_environment
    if path_kind == "web_traversal":
        external_model = context.project_root / "frontend" / "outside.model3.json"
        configured_path = "/live2d/../../outside.model3.json"
    else:
        external_model = context.project_root / "external" / "outside.model3.json"
        configured_path = str(external_model.resolve())
    _write_live2d_model(external_model)
    context = replace(context, live2d_model_path=configured_path)

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert _checks(report)["live2d_asset"].code == "live2d_model_path_outside_root"


@pytest.mark.parametrize(
    ("mutate", "check_name", "code"),
    [
        (lambda c: setattr(c.system, "runtime_profile", "development"), "effective_profile", "profile_not_golden"),
        (lambda c: setattr(c, "persona", "default"), "persona", "persona_mismatch"),
        (lambda c: setattr(c.services, "agent", "mock"), "llm_provider", "llm_provider_mismatch"),
        (lambda c: setattr(c.agent.llm_config, "model", "deepseek-v4-pro"), "llm_model", "llm_model_mismatch"),
        (lambda c: setattr(c.services, "tts", "mock"), "tts_provider", "tts_provider_mismatch"),
        (lambda c: setattr(c.tts, "model", "/snapshot/path"), "tts_model", "tts_model_not_stable"),
    ],
)
def test_golden_identity_and_provider_mismatches_fail(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
    mutate: Any,
    check_name: str,
    code: str,
) -> None:
    config, context, _ = golden_environment
    mutate(config)

    report = run_golden_preflight(config, context)

    assert report.ok is False
    assert _checks(report)[check_name].code == code


def test_complete_environment_passes_with_sanitized_metadata(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    report = run_golden_preflight(config, context)

    assert report.ok is True
    assert report.scope == "runtime"
    assert report.acceptance_ready is True
    assert all(check.ok for check in report.checks)
    assert report.metadata["runtime_profile"] == "golden"
    assert report.metadata["persona"] == "anima.v0.1"
    assert report.metadata["llm"] == {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "thinking": "disabled",
        "credential_present": True,
    }
    assert report.metadata["tts"]["provider"] == "alice_vc"
    assert report.metadata["tts"]["model"] == GOLDEN_QWEN_MODEL_ID
    assert report.metadata["tts"]["model_revision"] == "0123456789abcdef"
    assert report.metadata["gpu"]["device_name"] == "Test CUDA GPU"


def test_serialization_redacts_api_keys_bearer_tokens_and_sensitive_env_values(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment
    api_key = "sk-leak-me-123456789"
    opaque_token = "opaque-sensitive-value"
    config.agent.llm_config.api_key = api_key
    context = replace(
        context,
        env={
            **context.env,
            "DEEPSEEK_API_KEY": api_key,
            "PRIVATE_SIGNING_TOKEN": opaque_token,
        },
        cuda_probe=lambda: {
            "available": False,
            "reason": f"Bearer {api_key}; token={opaque_token}",
        },
    )

    serialized = run_golden_preflight(config, context).to_json()

    assert api_key not in serialized
    assert opaque_token not in serialized
    assert "Bearer" not in serialized
    assert "sk-leak" not in serialized
    assert "<redacted>" in serialized


def test_report_json_is_machine_readable_and_matches_dict(
    golden_environment: tuple[SimpleNamespace, GoldenPreflightContext, dict[str, Path]],
) -> None:
    config, context, _ = golden_environment

    report = run_golden_preflight(config, context)
    payload = json.loads(report.to_json())

    assert payload == report.to_dict()
    assert payload["ok"] is True
    assert payload["scope"] == "runtime"
    assert payload["acceptance_ready"] is True
    assert isinstance(payload["checks"], list)
    assert all(set(check) == {"name", "ok", "code", "detail"} for check in payload["checks"])
    assert isinstance(payload["metadata"], dict)
