from __future__ import annotations

from pathlib import Path

import pytest

from animetta.config.app import AppConfig
from animetta.config.persona.base import PersonaConfig
from animetta.config.runtime_reload import (
    RuntimeConfigReloader,
    apply_lightweight_llm_config,
    apply_runtime_config_to_contexts,
)
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
    for name in (
        "ANIMETTA_ASR",
        "ANIMETTA_TTS",
        "ANIMETTA_LLM",
        "ANIMETTA_LOCAL_LLM",
        "ANIMETTA_VAD",
    ):
        monkeypatch.setenv(name, "")
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
    assert result.to_dict()["preserved"] is False
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


def test_reload_missing_persona_preserves_previous_config(runtime_config_env):
    config_path, personas_dir, _ = runtime_config_env
    current = AppConfig.load(str(config_path))
    current._persona = PersonaConfig.load(current.persona, personas_dir=str(personas_dir))
    previous_prompt = current.get_system_prompt()

    (personas_dir / "test_anima.yaml").unlink()

    reloader = RuntimeConfigReloader(current, config_path=str(config_path), personas_dir=str(personas_dir))
    result = reloader.reload()

    assert result.ok is False
    assert result.version == 1
    assert result.error
    assert reloader.config is current
    assert reloader.config.get_system_prompt() == previous_prompt
    assert result.to_dict()["preserved"] is True


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


def test_reload_failure_does_not_mutate_shared_llm_settings(runtime_config_env):
    config_path, personas_dir, _ = runtime_config_env
    current = AppConfig.load(str(config_path))
    current._persona = PersonaConfig.load(current.persona, personas_dir=str(personas_dir))

    class Engine:
        model = "old-model"
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
        {"config": current, "runtime_config_version": 1, "llm_engine": engine},
    )()

    (personas_dir / "test_anima.yaml").write_text("name: [broken", encoding="utf-8")

    reloader = RuntimeConfigReloader(current, config_path=str(config_path), personas_dir=str(personas_dir))
    result = reloader.reload()
    if result.ok:
        apply_runtime_config_to_contexts(reloader.config, result.version, [ctx])

    assert result.ok is False
    assert engine.model == "old-model"
    assert engine.temperature == 0.1
    assert engine.top_p == 0.2
    assert engine.max_tokens == 64
    assert engine.system_prompt == "old prompt"
    assert ctx.config is current
    assert ctx.runtime_config_version == 1


def test_apply_runtime_config_replaces_active_session_config_version_and_prompt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "animetta.config.live2d.get_live2d_config",
        lambda: type("Live2DConfig", (), {"enabled": False})(),
    )

    class Config:
        model = "new-model"
        temperature = 0.7
        top_p = 0.8
        max_tokens = 256

    class Engine:
        model = "old-model"
        temperature = 0.1
        top_p = 0.2
        max_tokens = 64

        def __init__(self) -> None:
            self.system_prompt = "old prompt"

        def set_system_prompt(self, prompt: str) -> None:
            self.system_prompt = prompt

    runtime_config = type(
        "RuntimeConfig",
        (),
        {
            "persona": "test_anima",
            "agent": type("Agent", (), {"llm_config": Config()})(),
            "get_system_prompt": lambda self, live2d_prompt=None: "new prompt",
        },
    )()
    old_config = object()
    engine = Engine()
    ctx = type(
        "Ctx",
        (),
        {"config": old_config, "runtime_config_version": 1, "llm_engine": engine},
    )()

    result = apply_runtime_config_to_contexts(runtime_config, 2, [ctx])

    assert ctx.config is runtime_config
    assert ctx.runtime_config_version == 2
    assert engine.model == "new-model"
    assert engine.temperature == 0.7
    assert engine.top_p == 0.8
    assert engine.max_tokens == 256
    assert engine.system_prompt == "new prompt"
    assert result.to_dict() == {
        "version": 2,
        "persona": "test_anima",
        "sessions": 1,
        "prompt_warnings": [],
    }


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
