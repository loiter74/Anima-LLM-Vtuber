from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from animetta.config.manifest import EffectiveConfig, load_effective_config
from animetta.config.runtime_reload import (
    RuntimeConfigReloader,
    apply_lightweight_llm_config,
    apply_runtime_config_to_contexts,
)
from animetta.tracing.proxy import TracingProxy


def _write_persona(personas_dir: Path, identity: str) -> None:
    personas_dir.mkdir(parents=True, exist_ok=True)
    (personas_dir / "reload_test.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "Reload Test",
                "role": "测试角色",
                "identity": identity,
                "speaking_style": "测试语气",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _runtime_manifest(
    manifest_data: dict[str, Any],
    write_manifest,
    personas_dir: Path,
    *,
    profile: str = "test",
) -> tuple[Path, EffectiveConfig]:
    data = deepcopy(manifest_data)
    data["application"]["persona"] = "reload_test"
    path = write_manifest(data)
    config = load_effective_config(
        path,
        profile=profile,
        personas_dir=personas_dir,
    )
    return path, config


def test_reload_success_replaces_persona_snapshot_and_increments_version(
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "personas"
    _write_persona(personas_dir, "旧人设")
    config_path, current = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
    )
    assert "旧人设" in current.get_system_prompt()

    _write_persona(personas_dir, "新人设")
    reloader = RuntimeConfigReloader(
        current,
        config_path=config_path,
        personas_dir=personas_dir,
    )

    result = reloader.reload()

    assert result.ok is True
    assert result.version == 2
    assert result.refreshed == ["persona"]
    assert result.effective_hash == reloader.config.effective_hash
    assert result.semantic_hash == reloader.config.semantic_hash
    assert "新人设" in reloader.config.get_system_prompt()
    assert "旧人设" in current.get_system_prompt()
    assert reloader.config is not current


def test_reload_invalid_persona_preserves_previous_immutable_snapshot(
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "personas"
    _write_persona(personas_dir, "旧人设")
    config_path, current = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
    )
    previous_hashes = (current.effective_hash, current.semantic_hash)
    (personas_dir / "reload_test.yaml").write_text("name: [broken", encoding="utf-8")

    reloader = RuntimeConfigReloader(
        current,
        config_path=config_path,
        personas_dir=personas_dir,
    )
    result = reloader.reload()

    assert result.ok is False
    assert result.preserved is True
    assert result.version == 1
    assert result.restart_required == []
    assert reloader.config is current
    assert (result.effective_hash, result.semantic_hash) == previous_hashes
    assert "旧人设" in current.get_system_prompt()


def test_reload_allows_lightweight_llm_fields_but_preserves_engine_identity(
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "personas"
    _write_persona(personas_dir, "稳定人设")
    config_path, current = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
        profile="smoke",
    )
    data = deepcopy(manifest_data)
    data["application"]["persona"] = "reload_test"
    data["providers"]["llm"]["deepseek"].update(
        {"temperature": 0.41, "top_p": 0.77, "max_tokens": 333, "thinking": "disabled"}
    )
    write_manifest(data)

    reloader = RuntimeConfigReloader(
        current,
        config_path=config_path,
        personas_dir=personas_dir,
    )
    result = reloader.reload()

    assert result.ok is True
    assert result.refreshed == ["llm"]
    next_llm = reloader.config.agent.llm_config
    assert next_llm.temperature == 0.41
    assert next_llm.top_p == 0.77
    assert next_llm.max_tokens == 333
    assert next_llm.model == current.agent.llm_config.model
    assert (
        reloader.config.providers["llm"].public_identity()
        == current.providers["llm"].public_identity()
    )


@pytest.mark.parametrize(
    ("mutate", "expected_path"),
    [
        (
            lambda data: data["profiles"]["smoke"]["services"].update({"tts": "qwen-host"}),
            "services.tts",
        ),
        (
            lambda data: data["providers"]["llm"]["deepseek"].update({"model": "different-model"}),
            "providers.llm.model",
        ),
        (
            lambda data: data["providers"]["tts"]["mimo-tts"].update({"voice": "different-voice"}),
            "providers.tts.voice",
        ),
        (
            lambda data: data["providers"]["llm"]["deepseek"].update(
                {"base_url": "https://restart.invalid/v1"}
            ),
            "providers.llm.base_url",
        ),
        (
            lambda data: data["profiles"]["smoke"]["policy"].update(
                {"require_remote_identity": False}
            ),
            "policy.require_remote_identity",
        ),
    ],
)
def test_reload_rejects_restart_required_lifecycle_changes(
    mutate,
    expected_path: str,
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "personas"
    _write_persona(personas_dir, "稳定人设")
    config_path, current = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
        profile="smoke",
    )
    data = deepcopy(manifest_data)
    data["application"]["persona"] = "reload_test"
    mutate(data)
    write_manifest(data)

    reloader = RuntimeConfigReloader(
        current,
        config_path=config_path,
        personas_dir=personas_dir,
    )
    result = reloader.reload()

    assert result.ok is False
    assert result.preserved is True
    assert result.version == 1
    assert result.restart_required == [expected_path]
    assert reloader.config is current


def test_reload_rejects_profile_and_schema_changes_with_exact_paths(
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "personas"
    _write_persona(personas_dir, "稳定人设")
    config_path, current = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
        profile="test",
    )
    manifest_secrets.setenv("ANIMETTA_PROFILE", "smoke")
    reloader = RuntimeConfigReloader(
        current,
        config_path=config_path,
        personas_dir=personas_dir,
    )

    profile_result = reloader.reload()

    assert profile_result.restart_required == ["profile"]
    manifest_secrets.delenv("ANIMETTA_PROFILE")
    data = deepcopy(manifest_data)
    data["application"]["persona"] = "reload_test"
    data["schema_version"] = 2
    write_manifest(data)

    schema_result = reloader.reload()

    assert schema_result.restart_required == ["schema_version"]
    assert reloader.config is current


def test_reload_result_redacts_secrets_and_local_paths(
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "secret-home" / "personas"
    _write_persona(personas_dir, "稳定人设")
    config_path, current = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
    )
    (personas_dir / "reload_test.yaml").write_text("name: [broken", encoding="utf-8")
    reloader = RuntimeConfigReloader(
        current,
        config_path=config_path,
        personas_dir=personas_dir,
    )

    payload = reloader.reload().to_dict()

    assert "test-deepseek-secret" not in str(payload)
    assert str(tmp_path) not in str(payload)


def test_apply_runtime_config_updates_shared_snapshot_version_hashes_and_prompt(
    manifest_data,
    write_manifest,
    manifest_secrets,
    tmp_path: Path,
) -> None:
    personas_dir = tmp_path / "personas"
    _write_persona(personas_dir, "新人设")
    _, runtime_config = _runtime_manifest(
        manifest_data,
        write_manifest,
        personas_dir,
    )

    class Engine:
        model = "original-model"
        temperature = 0.1
        top_p = 0.2
        max_tokens = 64

        def __init__(self) -> None:
            self.system_prompt = "old prompt"

        def set_system_prompt(self, prompt: str) -> None:
            self.system_prompt = prompt

    engine = Engine()
    ctx = type(
        "Ctx",
        (),
        {
            "config": object(),
            "runtime_config_version": 1,
            "runtime_config_hash": "old",
            "runtime_semantic_hash": "old",
            "llm_engine": engine,
        },
    )()

    result = apply_runtime_config_to_contexts(runtime_config, 2, [ctx])

    assert ctx.config is runtime_config
    assert ctx.runtime_config_version == 2
    assert ctx.runtime_config_hash == runtime_config.effective_hash
    assert ctx.runtime_semantic_hash == runtime_config.semantic_hash
    assert engine.model == "original-model"
    assert engine.system_prompt != "old prompt"
    assert result.to_dict()["effective_hash"] == runtime_config.effective_hash


def test_apply_lightweight_llm_config_updates_proxy_target_without_model_swap() -> None:
    class Engine:
        model = "original-model"
        temperature = 0.1
        top_p = 0.2
        max_tokens = 64
        extra_body: dict[str, Any] = {}

    class Config:
        model = "restart-only-model"
        temperature = 0.8
        top_p = 0.9
        max_tokens = 512
        thinking = "disabled"

    engine = Engine()
    proxy = TracingProxy(engine, service_name="llm")

    apply_lightweight_llm_config(proxy, Config())

    assert engine.model == "original-model"
    assert engine.temperature == 0.8
    assert engine.top_p == 0.9
    assert engine.max_tokens == 512
    assert engine.extra_body == {"thinking": {"type": "disabled"}}
