"""Contract tests for the July 2026 golden runtime configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

import animetta.config.app as app_module
from animetta.config.app import AppConfig, clear_config_caches
from animetta.config.system import SystemConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_CONFIG = PROJECT_ROOT / "config" / "config.golden.yaml"


@pytest.fixture(autouse=True)
def isolated_golden_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Prevent developer environment overrides from changing the golden contract."""
    empty_env_file = tmp_path / ".env"
    empty_env_file.write_text("", encoding="utf-8")

    for name in (
        "ANIMETTA_CONFIG",
        "ANIMETTA_ENV_FILE",
        "ANIMETTA_ASR",
        "ANIMETTA_TTS",
        "ANIMETTA_LLM",
        "ANIMETTA_LOCAL_LLM",
        "ANIMETTA_VAD",
        "LLM_API_KEY",
        "LLM_MODEL",
        "ASR_API_KEY",
        "TTS_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("ANIMETTA_ENV_FILE", str(empty_env_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setattr(app_module, "_env_file_loaded", False)
    clear_config_caches()
    yield
    clear_config_caches()


def test_system_config_defaults_to_safe_non_persistent_development_mode():
    config = SystemConfig()

    assert config.runtime_profile == "development"
    assert config.long_term_memory_mode == "off"
    assert config.enable_tools is True
    assert config.enable_subtitle_translation is True
    assert config.enable_active_memes is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_profile", "production"),
        ("long_term_memory_mode", "enabled"),
    ],
)
def test_system_config_rejects_unknown_runtime_modes(field: str, value: str):
    with pytest.raises(ValidationError) as exc_info:
        SystemConfig(**{field: value})

    assert exc_info.value.errors()[0]["loc"] == (field,)
    assert exc_info.value.errors()[0]["type"] == "literal_error"


def test_animetta_config_selects_the_golden_profile(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANIMETTA_CONFIG", str(GOLDEN_CONFIG))

    config = AppConfig.load()

    assert config.persona == "anima.v0.1"
    assert config.services.agent == "deepseek"
    assert config.services.tts == "alice_vc"
    assert config.services.local_llm is None
    assert config.local_llm is None
    assert config.system.runtime_profile == "golden"
    assert config.system.long_term_memory_mode == "off"
    assert config.system.debug is False
    assert config.system.enable_tools is False
    assert config.system.enable_subtitle_translation is False
    assert config.system.enable_active_memes is False
    assert config.humor.enabled is False


def test_golden_profile_uses_non_thinking_deepseek_v4_flash(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ANIMETTA_CONFIG", str(GOLDEN_CONFIG))

    config = AppConfig.load()

    assert config.agent is not None
    assert config.agent.llm_config.type == "deepseek"
    assert config.agent.llm_config.model == "deepseek-v4-flash"
    assert config.agent.llm_config.thinking == "disabled"


def test_golden_profile_uses_alice_icl_voice_clone_with_stable_model_id(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ANIMETTA_CONFIG", str(GOLDEN_CONFIG))

    config = AppConfig.load()

    assert config.tts is not None
    assert config.tts.type == "qwen3"
    assert config.tts.model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert config.tts.ref_audio_path == "config/personas/voices/alice_ref.wav"
    assert config.tts.ref_text.strip()
    assert config.tts.x_vector_only is False
