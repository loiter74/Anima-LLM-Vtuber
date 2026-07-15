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


def test_docker_profiles_match_release_and_cpu_remote_roles():
    manifest = yaml.safe_load((ROOT / "config" / "animetta.yaml").read_text(encoding="utf-8"))
    expected = {
        "docker-compose.yml": "production",
        "docker-compose.cpu.yml": "${ANIMETTA_PROFILE:-smoke}",
    }
    for compose_file, profile in expected.items():
        env = _compose_env(compose_file)
        assert env["ANIMETTA_PROFILE"] == profile
    assert manifest["profiles"]["production"]["services"]["llm"] == "deepseek"
    assert manifest["profiles"]["smoke"]["services"]["llm"] == "deepseek"
    assert manifest["profiles"]["smoke"]["services"]["tts"] == "mimo-tts"


def test_default_runtime_persona_is_anima_v01():
    config = yaml.safe_load((ROOT / "config" / "animetta.yaml").read_text(encoding="utf-8"))
    assert config["application"]["persona"] == "anima.v0.1"
