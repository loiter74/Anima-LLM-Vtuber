"""Runtime defaults for Docker deployment."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose_env(path: str) -> dict[str, str]:
    compose = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    env_entries = compose["services"]["animetta"]["environment"]
    env: dict[str, str] = {}
    for entry in env_entries:
        key, value = entry.split("=", 1)
        env[key] = value
    return env


def test_docker_defaults_use_real_llm_provider():
    for compose_file in ("docker-compose.yml", "docker-compose.cpu.yml"):
        env = _compose_env(compose_file)
        assert env["ANIMETTA_LLM"] == "deepseek"


def test_default_runtime_persona_is_anima_v01():
    config = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert config["persona"] == "anima.v0.1"
