from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from animetta.config.manifest import (
    DEFAULT_MANIFEST_PATH,
    ApplicationManifest,
    ConfiguredProvider,
    EnvironmentResolutionError,
    LegacySelectorError,
    ManifestValidationError,
    ProfileSelectionError,
    ProviderPolicyError,
    RuntimeSettings,
    _freeze_json,
    _hashable_value,
    _resolve_environment_value,
    _resolve_selected_declaration,
    _validate_environment_locations,
    load_effective_config,
)
from animetta.config.providers.asr import MimoASRConfig, MockASRConfig
from animetta.config.providers.llm import DeepSeekLLMConfig, MockLLMConfig
from animetta.config.providers.tts import (
    FailoverTTSConfig,
    MimoTTSConfig,
    MockTTSConfig,
    RemoteTTSConfig,
)
from animetta.config.providers.vad import MimoVADConfig, MockVADConfig
from animetta.config.runtime_reload import RuntimeConfigReloader

pytestmark = pytest.mark.config_unit
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_settings_allow_full_remote_tts_generation_window() -> None:
    settings = RuntimeSettings(tts_timeout_seconds=120.0)

    assert settings.tts_timeout_seconds == 120.0


def test_application_snapshot_json_is_validated_and_canonicalized() -> None:
    application = ApplicationManifest.model_validate(
        {
            "persona": "anima.v0.1",
            "system": {"host": "127.0.0.1", "port": 12394},
            "observability": json.dumps({"enabled": False}),
            "humor": json.dumps({"enabled": False}),
        }
    )
    assert application.observability["enabled"] is False
    assert application.humor["enabled"] is False

    with pytest.raises(ValidationError, match="snapshot must contain valid JSON"):
        ApplicationManifest.model_validate(
            {
                "persona": "anima.v0.1",
                "system": {"host": "127.0.0.1", "port": 12394},
                "observability": "{invalid-json",
                "humor": {},
            }
        )


@pytest.mark.parametrize(
    ("profile", "expected_services", "allow_mock"),
    [
        (
            "test",
            {"llm": "mock", "asr": "mock", "tts": "mock", "vad": "mock"},
            True,
        ),
        (
            "smoke",
            {
                "llm": "deepseek",
                "asr": "mimo-asr",
                "tts": "mimo-tts",
                "vad": "mimo-vad",
            },
            False,
        ),
        (
            "production",
            {
                "llm": "deepseek",
                "asr": "mimo-asr",
                "tts": "qwen-host",
                "vad": "mimo-vad",
            },
            False,
        ),
        (
            "selftest",
            {
                "llm": "deepseek",
                "asr": "mimo-asr",
                "tts": "qwen-host",
                "vad": "mimo-vad",
            },
            False,
        ),
    ],
)
def test_cfg_001_profiles_resolve_exact_service_references(
    profile: str,
    expected_services: dict[str, str],
    allow_mock: bool,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = write_manifest(manifest_data)

    effective = load_effective_config(path, profile=profile)

    assert effective.profile == profile
    assert effective.services.model_dump() == expected_services
    assert effective.policy.allow_mock is allow_mock
    assert set(effective.providers) == {"llm", "asr", "tts", "vad"}


def test_cfg_002_profile_is_mandatory_and_must_exist(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = write_manifest(manifest_data)

    with pytest.raises(ProfileSelectionError, match="ANIMETTA_PROFILE.*production"):
        load_effective_config(path)

    with pytest.raises(ProfileSelectionError, match="unknown.*test.*smoke.*production"):
        load_effective_config(path, profile="unknown")


@pytest.mark.parametrize("missing_service", ["llm", "asr", "tts", "vad"])
def test_cfg_003_profile_requires_all_service_references(
    missing_service: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    del data["profiles"]["smoke"]["services"][missing_service]

    with pytest.raises(ManifestValidationError, match=missing_service):
        load_effective_config(write_manifest(data), profile="smoke")


def test_cfg_003_unknown_provider_reference_is_rejected(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["profiles"]["smoke"]["services"]["tts"] = "not-declared"

    with pytest.raises(ManifestValidationError, match="tts.*not-declared"):
        load_effective_config(write_manifest(data), profile="smoke")


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda data: data.update(schema_version=99), "schema_version"),
        (lambda data: data.update(unexpected=True), "unexpected"),
        (lambda data: data["profiles"]["test"].update(unexpected=True), "unexpected"),
    ],
)
def test_cfg_004_unknown_schema_or_fields_are_rejected(
    mutate,
    expected: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    mutate(data)

    with pytest.raises(ManifestValidationError, match=expected):
        load_effective_config(write_manifest(data), profile="test")


def test_cfg_005_yaml_merge_keys_are_rejected_before_safe_load(
    tmp_path: Path,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "animetta.yaml"
    path.write_text(
        """
schema_version: 1
application: &application
  persona: anima.v0.1
  system:
    host: ${ANIMETTA_HOST}
    port: ${ANIMETTA_PORT}
providers: {llm: {}, asr: {}, tts: {}, vad: {}}
profiles:
  test:
    <<: *application
    services: {llm: mock, asr: mock, tts: mock, vad: mock}
    policy: {allow_mock: true, require_remote_identity: false}
    runtime: {}
  smoke: {services: {llm: mock, asr: mock, tts: mock, vad: mock}, policy: {allow_mock: false, require_remote_identity: true}, runtime: {}}
  production: {services: {llm: mock, asr: mock, tts: mock, vad: mock}, policy: {allow_mock: false, require_remote_identity: true}, runtime: {}}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ManifestValidationError, match="merge"):
        load_effective_config(path, profile="test")


def test_cfg_005_profile_inheritance_field_is_rejected(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["profiles"]["smoke"]["extends"] = "test"

    with pytest.raises(ManifestValidationError, match="extends"):
        load_effective_config(write_manifest(data), profile="smoke")


@pytest.mark.parametrize("category", ["llm", "asr", "tts", "vad"])
def test_cfg_006_real_profiles_reject_explicit_mock(
    category: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["profiles"]["smoke"]["services"][category] = "mock"

    with pytest.raises(ProviderPolicyError, match=f"smoke.*{category}.*mock"):
        load_effective_config(write_manifest(data), profile="smoke")


def test_cfg_007_only_selected_endpoints_and_secrets_are_expanded(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = write_manifest(manifest_data)

    effective = load_effective_config(path, profile="production")

    assert effective.application.system.host == "127.0.0.1"
    assert effective.application.system.port == 12394
    assert effective.providers["llm"].declaration["api_key"] == "test-deepseek-secret"
    assert effective.providers["asr"].declaration["api_key"] == "test-mimo-secret"
    assert effective.providers["tts"].declaration["api_key"] == "test-qwen-secret"
    assert effective.providers["tts"].declaration["base_url"] == (
        "http://host.docker.internal:8767"
    )


def test_cfg_007_unselected_real_provider_secrets_are_not_required(
    manifest_data: dict[str, Any],
    write_manifest,
    isolated_manifest_env: pytest.MonkeyPatch,
) -> None:
    isolated_manifest_env.setenv("ANIMETTA_HOST", "127.0.0.1")
    isolated_manifest_env.setenv("ANIMETTA_PORT", "12394")

    effective = load_effective_config(write_manifest(manifest_data), profile="test")

    assert all(provider.type == "mock" for provider in effective.providers.values())


@pytest.mark.parametrize(
    ("path_parts", "expression"),
    [
        (("application", "persona"), "${ANIMETTA_PERSONA}"),
        (("providers", "llm", "deepseek", "model"), "${DEEPSEEK_MODEL}"),
        (("providers", "tts", "qwen-host", "voice"), "${QWEN_VOICE}"),
        (("profiles", "smoke", "runtime", "tts_timeout_seconds"), "${TTS_TIMEOUT}"),
    ],
)
def test_cfg_008_business_fields_reject_environment_expansion(
    path_parts: tuple[str, ...],
    expression: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    target: Any = data
    for part in path_parts[:-1]:
        target = target[part]
    target[path_parts[-1]] = expression

    with pytest.raises(ManifestValidationError, match=re.escape(".".join(path_parts))):
        load_effective_config(write_manifest(data), profile="smoke")


def test_cfg_008_required_selected_secret_must_be_present(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    manifest_secrets.delenv("DEEPSEEK_API_KEY")

    with pytest.raises(EnvironmentResolutionError, match="DEEPSEEK_API_KEY") as exc_info:
        load_effective_config(write_manifest(manifest_data), profile="smoke")

    assert "test-mimo-secret" not in str(exc_info.value)


def test_cfg_008_required_host_endpoint_must_be_present(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    manifest_secrets.delenv("QWEN_HOST_TTS_URL")

    with pytest.raises(EnvironmentResolutionError, match="QWEN_HOST_TTS_URL"):
        load_effective_config(write_manifest(manifest_data), profile="production")


@pytest.mark.parametrize(
    "selector",
    [
        "ANIMETTA_CONFIG",
        "ANIMETTA_LLM",
        "ANIMETTA_ASR",
        "ANIMETTA_TTS",
        "ANIMETTA_VAD",
        "ANIMETTA_LOCAL_LLM",
        "ANIMETTA_BASE_MODEL_PATH",
        "ANIMETTA_LORA_PATH",
        "VITE_API_URL",
    ],
)
def test_cfg_009_legacy_selectors_fail_with_migration_guidance(
    selector: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    manifest_secrets.setenv(selector, "legacy-value")

    with pytest.raises(LegacySelectorError, match=selector) as exc_info:
        load_effective_config(write_manifest(manifest_data), profile="test")

    assert "ANIMETTA_PROFILE" in str(exc_info.value)
    assert "legacy-value" not in str(exc_info.value)


def test_cfg_009_secret_default_syntax_is_rejected(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["llm"]["deepseek"]["api_key"] = "${DEEPSEEK_API_KEY:unsafe}"

    with pytest.raises(ManifestValidationError, match="default.*api_key"):
        load_effective_config(write_manifest(data), profile="smoke")


def test_cfg_010_effective_config_and_nested_provider_data_are_immutable(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(write_manifest(manifest_data), profile="production")

    with pytest.raises(ValidationError, match="frozen"):
        effective.profile = "smoke"  # type: ignore[misc]
    with pytest.raises(TypeError):
        effective.providers["llm"] = effective.providers["tts"]  # type: ignore[index]
    with pytest.raises(TypeError):
        effective.providers["tts"].declaration["voice"] = "not-alice"  # type: ignore[index]


def test_cfg_011_hashes_are_stable_and_exclude_secret_values(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = write_manifest(manifest_data)
    first = load_effective_config(path, profile="production")

    manifest_secrets.setenv("DEEPSEEK_API_KEY", "rotated-deepseek-secret")
    manifest_secrets.setenv("MIMO_API_KEY", "rotated-mimo-secret")
    manifest_secrets.setenv("QWEN_TTS_API_KEY", "rotated-qwen-secret")
    rotated = load_effective_config(path, profile="production")

    assert rotated.effective_hash == first.effective_hash
    assert rotated.semantic_hash == first.semantic_hash
    for secret in (
        "test-deepseek-secret",
        "test-mimo-secret",
        "test-qwen-secret",
        "rotated-deepseek-secret",
        "rotated-mimo-secret",
        "rotated-qwen-secret",
    ):
        assert secret not in first.effective_hash
        assert secret not in first.semantic_hash


def test_cfg_011_semantic_hash_excludes_endpoints_but_effective_hash_includes_them(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = write_manifest(manifest_data)
    first = load_effective_config(path, profile="production")

    manifest_secrets.setenv("ANIMETTA_HOST", "0.0.0.0")
    manifest_secrets.setenv("ANIMETTA_PORT", "22394")
    manifest_secrets.setenv("QWEN_HOST_TTS_URL", "http://qwen-host.other:9001")
    moved = load_effective_config(path, profile="production")

    assert moved.semantic_hash == first.semantic_hash
    assert moved.effective_hash != first.effective_hash


def test_cfg_011_hashes_are_independent_of_mapping_order(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    first = load_effective_config(write_manifest(manifest_data), profile="production")
    reordered = deepcopy(manifest_data)
    reordered["providers"] = dict(reversed(list(reordered["providers"].items())))
    for category, declarations in list(reordered["providers"].items()):
        reordered["providers"][category] = dict(reversed(list(declarations.items())))
    reordered["profiles"] = dict(reversed(list(reordered["profiles"].items())))

    second = load_effective_config(write_manifest(reordered), profile="production")

    assert second.effective_hash == first.effective_hash
    assert second.semantic_hash == first.semantic_hash


def test_cfg_012_public_status_is_sanitized_and_separates_provider_identities(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["tts"]["qwen-host"]["base_url"] = "C:/Users/private/host"
    effective = load_effective_config(write_manifest(data), profile="production")

    public = effective.to_public_dict(
        resolved_identities={
            "tts": {
                "type": "mimo",
                "provider": "mimo",
                "model": "mimo-v2.5-tts",
                "voice": "other",
            }
        }
    )

    assert public["profile"] == "production"
    assert public["version"] == 1
    assert public["effective_hash"] == effective.effective_hash
    assert public["semantic_hash"] == effective.semantic_hash
    assert public["providers"]["asr"]["configured"]["type"] == "mimo"
    assert public["providers"]["tts"] == {
        "configured": {
            "name": "qwen-host",
            "type": "remote",
            "provider": "qwen3-tts-gguf-host",
            "model": "Qwen3-TTS-1.7B-Base",
            "voice": "tosaka-rin-cn",
        },
        "resolved": {
            "type": "mimo",
            "provider": "mimo",
            "model": "mimo-v2.5-tts",
            "voice": "other",
        },
        "ready": False,
        "error": "identity_mismatch",
    }
    serialized = str(public)
    assert "test-deepseek-secret" not in serialized
    assert "test-mimo-secret" not in serialized
    assert "test-qwen-secret" not in serialized
    assert "qwen-tts.test" not in serialized
    assert "C:/Users/private" not in serialized


@pytest.mark.parametrize("profile", ["test", "smoke", "selftest", "production"])
def test_repository_manifest_resolves_every_declared_profile(
    profile: str,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(
        PROJECT_ROOT / "config" / "animetta.yaml",
        profile=profile,
    )

    assert effective.profile == profile
    assert set(effective.providers) == {"llm", "asr", "tts", "vad"}


@pytest.mark.parametrize("profiles", [{"test", "smoke"}, {"test", "smoke", "production", "extra"}])
def test_manifest_requires_exact_profile_set(
    profiles: set[str],
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["profiles"] = {
        name: data["profiles"].get(name, data["profiles"]["test"]) for name in profiles
    }

    with pytest.raises(ManifestValidationError, match="profiles must be exactly"):
        load_effective_config(write_manifest(data), profile="test")


def test_missing_manifest_path_is_reported(
    tmp_path: Path,
    isolated_manifest_env: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ManifestValidationError, match="not found"):
        load_effective_config(tmp_path / "missing.yaml", profile="test")


@pytest.mark.parametrize("contents", ["schema_version: [", "- not\n- a\n- mapping"])
def test_invalid_yaml_or_non_mapping_root_is_rejected(
    contents: str,
    tmp_path: Path,
    isolated_manifest_env: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "animetta.yaml"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ManifestValidationError):
        load_effective_config(path, profile="test")


def test_environment_reference_inside_list_is_rejected_with_its_index(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["llm"]["deepseek"]["scopes"] = ["${DEEPSEEK_SCOPE}"]

    with pytest.raises(ManifestValidationError, match=r"scopes\.0"):
        load_effective_config(write_manifest(data), profile="smoke")


def test_environment_reference_must_occupy_entire_allowed_field(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["llm"]["deepseek"]["base_url"] = "${DEEPSEEK_HOST}/v1"

    with pytest.raises(ManifestValidationError, match="entire field"):
        load_effective_config(write_manifest(data), profile="smoke")


def test_selected_provider_lists_are_frozen_and_hashable() -> None:
    assert _freeze_json(["chat", "tools"]) == ("chat", "tools")


@pytest.mark.parametrize(
    ("profile", "expected_types"),
    [
        (
            "test",
            {
                "llm": MockLLMConfig,
                "asr": MockASRConfig,
                "tts": MockTTSConfig,
                "vad": MockVADConfig,
            },
        ),
        (
            "smoke",
            {
                "llm": DeepSeekLLMConfig,
                "asr": MimoASRConfig,
                "tts": MimoTTSConfig,
                "vad": MimoVADConfig,
            },
        ),
        (
            "production",
            {
                "llm": DeepSeekLLMConfig,
                "asr": MimoASRConfig,
                "tts": RemoteTTSConfig,
                "vad": MimoVADConfig,
            },
        ),
        (
            "selftest",
            {
                "llm": DeepSeekLLMConfig,
                "asr": MimoASRConfig,
                "tts": RemoteTTSConfig,
                "vad": MimoVADConfig,
            },
        ),
    ],
)
def test_selected_declarations_resolve_to_registered_typed_configs(
    profile: str,
    expected_types: dict[str, type],
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(write_manifest(manifest_data), profile=profile)

    assert {
        category: type(effective.typed_provider(category))
        for category in ("llm", "asr", "tts", "vad")
    } == expected_types


def test_effective_config_projects_the_runtime_compatibility_view(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(write_manifest(manifest_data), profile="smoke")

    assert effective.persona == "anima.v0.1"
    assert effective.system.host == "127.0.0.1"
    assert effective.system.port == 12394
    assert effective.system.runtime_profile == "smoke"
    assert effective.system.golden_tts_timeout_seconds == 20.0
    assert effective.services.agent == "deepseek"
    assert isinstance(effective.asr, MimoASRConfig)
    assert isinstance(effective.tts, MimoTTSConfig)
    assert isinstance(effective.vad, MimoVADConfig)
    assert isinstance(effective.agent.llm_config, DeepSeekLLMConfig)
    assert effective.local_llm is None
    assert effective.humor.enabled is False
    assert effective.observability.enabled is True
    assert effective.bilibili is None


@pytest.mark.parametrize(
    ("section", "invalid_values", "message"),
    [
        ("observability", {"invented_selector": True}, "invented_selector"),
        ("humor", {"candidate_count": 0}, "candidate_count"),
    ],
)
def test_application_sections_are_strictly_validated_during_load(
    section: str,
    invalid_values: dict[str, Any],
    message: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["application"][section] = invalid_values

    with pytest.raises(ManifestValidationError, match=message):
        load_effective_config(write_manifest(data), profile="test")


def test_application_section_snapshots_are_deeply_immutable_and_hash_stable(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["application"]["observability"] = {
        "enabled": True,
        "privacy": {"production": "redacted"},
    }
    data["application"]["humor"] = {
        "enabled": False,
        "allowed_styles": ["affiliative"],
    }
    effective = load_effective_config(write_manifest(data), profile="test")
    before_hash = effective.effective_hash

    with pytest.raises(TypeError):
        cast(Any, effective.application.observability)["enabled"] = False
    with pytest.raises(TypeError):
        cast(Any, effective.application.observability["privacy"])["production"] = "full"
    with pytest.raises(TypeError):
        cast(Any, effective.application.humor)["allowed_styles"][0] = "tampered"

    assert effective.application.observability["enabled"] is True
    assert effective.application.humor["allowed_styles"] == ("affiliative",)
    assert effective.effective_hash == before_hash


def test_default_manifest_entrypoints_are_independent_of_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    effective = load_effective_config(profile="test")
    reloader = RuntimeConfigReloader(effective)

    assert DEFAULT_MANIFEST_PATH.is_absolute()
    assert effective.persona == "anima.v0.1"
    assert reloader.config_path == DEFAULT_MANIFEST_PATH


def test_default_production_selects_dashscope_with_host_qwen_fallback(
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(profile="production")
    selected = effective.providers["tts"]
    typed = effective.typed_provider("tts")

    assert selected.name == "dashscope-local-failover"
    assert selected.public_identity() == {
        "name": "dashscope-local-failover",
        "type": "failover",
        "provider": "failover",
        "model": None,
        "voice": None,
    }
    assert typed.type == "failover"
    assert isinstance(typed, FailoverTTSConfig)
    assert typed.primary.model == "qwen3-tts-instruct-flash-realtime"
    assert typed.primary.voice == "Seren"
    assert typed.fallback.model == "Qwen3-TTS-1.7B-Base"
    assert typed.fallback.voice == "tosaka-rin-cn"
    assert typed.fallback.base_url == "http://host.docker.internal:8767"


def test_repository_selftest_uses_local_qwen_without_changing_production(
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    selftest = load_effective_config(profile="selftest")
    production = load_effective_config(profile="production")

    assert selftest.profile == "selftest"
    assert selftest.services.tts == "qwen-host"
    assert selftest.tts.type == "remote"
    assert selftest.tts.provider == "qwen3-tts-gguf-host"
    assert selftest.tts.model == "Qwen3-TTS-1.7B-Base"
    assert selftest.tts.voice == "tosaka-rin-cn"
    assert selftest.system.tts_timeout_seconds == 120.0
    assert production.services.tts == "dashscope-local-failover"


def test_reloader_defaults_to_the_manifest_that_produced_effective_config(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    path = write_manifest(manifest_data)
    effective = load_effective_config(path, profile="test")

    assert RuntimeConfigReloader(effective).config_path == path.resolve()


def test_effective_config_builds_persona_and_live2d_system_prompt(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(write_manifest(manifest_data), profile="test")
    persona = effective.get_persona()

    assert persona.name == "Anima"
    assert effective.get_persona() is not persona
    assert "expressions" in effective.get_system_prompt(live2d_prompt="expressions")


def test_selected_provider_schema_rejects_unknown_fields(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["llm"]["deepseek"]["invented_selector"] = "not-allowed"

    with pytest.raises(ManifestValidationError, match="invented_selector"):
        load_effective_config(write_manifest(data), profile="smoke")


def test_typed_provider_instances_cannot_mutate_effective_config(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(write_manifest(manifest_data), profile="production")
    first = effective.typed_provider("tts")
    first.voice = "tampered"

    assert effective.typed_provider("tts").voice == "tosaka-rin-cn"


@pytest.mark.parametrize("port", ["not-a-port", "70000"])
def test_application_port_must_resolve_to_valid_tcp_port(
    port: str,
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    manifest_secrets.setenv("ANIMETTA_PORT", port)

    with pytest.raises(ManifestValidationError, match="application.system.port"):
        load_effective_config(write_manifest(manifest_data), profile="test")


def test_selected_provider_requires_non_empty_type(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["llm"]["mock"]["type"] = ""

    with pytest.raises(ManifestValidationError, match="non-empty type"):
        load_effective_config(write_manifest(data), profile="test")


def test_literal_secret_is_redacted_from_hashes(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    data = deepcopy(manifest_data)
    data["providers"]["llm"]["deepseek"]["api_key"] = "literal-secret"

    effective = load_effective_config(write_manifest(data), profile="smoke")

    assert "literal-secret" not in effective.effective_hash
    assert "literal-secret" not in effective.semantic_hash


def test_internal_environment_guard_rejects_unvalidated_partial_reference() -> None:
    with pytest.raises(ManifestValidationError, match="Invalid environment reference"):
        _resolve_environment_value("${HOST}/v1", ("providers", "llm", "x", "base_url"))


def test_hash_canonicalizer_handles_missing_raw_list_values() -> None:
    assert _hashable_value(None, ["one"], ("example",), semantic=False) == ["one"]


def test_hash_canonicalizer_redacts_secret_without_raw_string() -> None:
    assert _hashable_value(None, "resolved-secret", ("api_key",), semantic=False) == (
        "<redacted-secret>"
    )


def test_typed_provider_rejects_unregistered_provider_schema() -> None:
    provider = ConfiguredProvider(
        category="llm",
        name="missing",
        type="not-registered",
        declaration_json='{"type":"not-registered"}',
    )

    with pytest.raises(ManifestValidationError, match="No registered config schema"):
        provider.typed_config()


def test_effective_config_rejects_unknown_typed_provider_category(
    manifest_data: dict[str, Any],
    write_manifest,
    manifest_secrets: pytest.MonkeyPatch,
) -> None:
    effective = load_effective_config(write_manifest(manifest_data), profile="test")

    with pytest.raises(KeyError, match="unknown"):
        effective.typed_provider("unknown")


def test_environment_location_validator_accepts_literal_list_values() -> None:
    _validate_environment_locations({"values": ["literal"]})


def test_selected_declaration_resolver_preserves_literal_list_values() -> None:
    assert _resolve_selected_declaration(
        {"values": ["literal"]},
        ("providers", "llm", "example"),
    ) == {"values": ["literal"]}
