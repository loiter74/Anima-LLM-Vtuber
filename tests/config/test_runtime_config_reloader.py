from __future__ import annotations

from pathlib import Path

import pytest

from animetta.config.app import AppConfig
from animetta.config.persona.base import PersonaConfig
from animetta.config.runtime_reload import RuntimeConfigReloader, apply_lightweight_llm_config
from animetta.tracing.proxy import TracingProxy


def _write_runtime_config(root: Path, *, persona_identity: str, llm_top_p: float = 0.93) -> Path:
    config_dir = root / "config"
    personas_dir = config_dir / "personas"
    personas_dir.mkdir(parents=True)

    (config_dir / "config.yaml").write_text(
        """
persona: test_anima
services:
  asr: mock
  tts: mock
  agent: mock
  vad: mock
""".strip(),
        encoding="utf-8",
    )
    (config_dir / "services.yaml").write_text(
        f"""
asr:
  mock:
    type: mock
tts:
  mock:
    type: mock
llm:
  mock:
    memory_enabled: false
    llm_config:
      type: mock
      temperature: 0.9
      top_p: {llm_top_p}
      max_tokens: 128
vad:
  mock:
    type: mock
""".strip(),
        encoding="utf-8",
    )
    (personas_dir / "test_anima.yaml").write_text(
        f"""
name: Test Anima
role: 测试角色
identity: {persona_identity}
speaking_style: 测试语气
""".strip(),
        encoding="utf-8",
    )
    return config_dir / "config.yaml"


@pytest.fixture
def runtime_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import animetta.config.app as app_module

    config_path = _write_runtime_config(tmp_path, persona_identity="旧人设")
    config_dir = tmp_path / "config"
    monkeypatch.setattr(app_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(app_module, "SERVICES_DIR", config_dir / "services")
    app_module.clear_config_caches()
    return config_path, config_dir / "personas", app_module


def test_reload_success_replaces_persona_and_increments_version(runtime_config_env):
    config_path, personas_dir, _ = runtime_config_env
    current = AppConfig.load(str(config_path))
    current._persona = PersonaConfig.load(current.persona, personas_dir=str(personas_dir))
    assert current.get_system_prompt().find("旧人设") >= 0

    (personas_dir / "test_anima.yaml").write_text(
        """
name: Test Anima
role: 测试角色
identity: 新人设
speaking_style: 新语气
""".strip(),
        encoding="utf-8",
    )

    reloader = RuntimeConfigReloader(current, config_path=str(config_path), personas_dir=str(personas_dir))
    result = reloader.reload()

    assert result.ok is True
    assert result.persona == "test_anima"
    assert result.version == 2
    assert "persona" in result.refreshed
    assert "llm" in result.refreshed
    assert reloader.config.get_system_prompt().find("新人设") >= 0
    assert reloader.config.get_system_prompt().find("旧人设") == -1


def test_reload_invalid_persona_preserves_previous_config(runtime_config_env):
    config_path, personas_dir, _ = runtime_config_env
    current = AppConfig.load(str(config_path))
    current._persona = PersonaConfig.load(current.persona, personas_dir=str(personas_dir))

    (personas_dir / "test_anima.yaml").write_text("name: [broken", encoding="utf-8")

    reloader = RuntimeConfigReloader(current, config_path=str(config_path), personas_dir=str(personas_dir))
    result = reloader.reload()

    assert result.ok is False
    assert result.version == 1
    assert result.error
    assert reloader.config is current
    assert "旧人设" in reloader.config.get_system_prompt()


def test_reload_invalid_llm_config_preserves_previous_llm(runtime_config_env):
    config_path, _, app_module = runtime_config_env
    current = AppConfig.load(str(config_path))
    previous_llm = current.agent.llm_config
    assert previous_llm.top_p == 0.93

    services_path = config_path.parent / "services.yaml"
    services_path.write_text(services_path.read_text(encoding="utf-8").replace("top_p: 0.93", "top_p: 2.0"), encoding="utf-8")
    app_module.clear_config_caches()

    reloader = RuntimeConfigReloader(current, config_path=str(config_path), personas_dir=str(config_path.parent / "personas"))
    result = reloader.reload()

    assert result.ok is False
    assert result.version == 1
    assert reloader.config.agent.llm_config is previous_llm
    assert reloader.config.agent.llm_config.top_p == 0.93


def test_reload_result_redacts_secrets(runtime_config_env, monkeypatch: pytest.MonkeyPatch):
    config_path, personas_dir, _ = runtime_config_env
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-value")
    current = AppConfig.load(str(config_path))

    reloader = RuntimeConfigReloader(current, config_path=str(config_path), personas_dir=str(personas_dir))
    result = reloader.reload()

    payload = result.to_dict()
    assert "sk-secret-value" not in str(payload)


def test_apply_lightweight_llm_config_updates_tracing_proxy_target():
    class Engine:
        model = "old-model"
        temperature = 0.1
        top_p = 0.2
        max_tokens = 64
        extra_body = {}

    class Config:
        model = "deepseek-v4-flash"
        temperature = 0.8
        top_p = 0.9
        max_tokens = 512
        thinking = "disabled"

    engine = Engine()
    proxy = TracingProxy(engine, service_name="llm")

    apply_lightweight_llm_config(proxy, Config())

    assert engine.model == "deepseek-v4-flash"
    assert engine.temperature == 0.8
    assert engine.top_p == 0.9
    assert engine.max_tokens == 512
    assert engine.extra_body == {"thinking": {"type": "disabled"}}
