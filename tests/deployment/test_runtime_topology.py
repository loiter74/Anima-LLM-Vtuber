from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LEGACY_SELECTORS = (
    "ANIMETTA_CONFIG",
    "ANIMETTA_LLM",
    "ANIMETTA_ASR",
    "ANIMETTA_TTS",
    "ANIMETTA_VAD",
    "ANIMETTA_LOCAL_LLM",
    "VITE_API_URL",
)


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_image_installs_only_core_runtime_dependencies() -> None:
    dockerfile = _text("Dockerfile")

    assert "requirements-core.txt" in dockerfile
    assert "requirements-local-ai.txt" not in dockerfile
    assert "requirements-qwen-tts.txt" not in dockerfile
    assert "Dockerfile.cuda" not in dockerfile
    assert "https://deb.debian.org" in dockerfile
    assert "Acquire::Retries=5" in dockerfile


def test_build_context_excludes_reference_audio_from_all_images() -> None:
    dockerignore = _text(".dockerignore")

    assert "config/personas/voices/" in dockerignore.splitlines()


def test_build_context_excludes_local_frontend_package_cache() -> None:
    dockerignore = _text(".dockerignore")

    assert "frontend/.pnpm-store/" in dockerignore.splitlines()


def test_qwen_image_owns_gpu_dependencies_and_standalone_entrypoint() -> None:
    dockerfile = _text("Dockerfile.qwen-tts")

    assert "requirements-qwen-tts.txt" in dockerfile
    assert "python -m animetta_qwen_tts" in dockerfile
    assert "nvidia/cuda" in dockerfile
    assert "frontend" not in dockerfile.lower()
    assert "gcc" in dockerfile
    assert "libc6-dev" in dockerfile
    assert "ENV CC=/usr/bin/gcc" in dockerfile
    assert "https://deb.debian.org" in dockerfile
    assert "Acquire::Retries=5" in dockerfile
    assert "COPY src/ src/" not in dockerfile
    assert "COPY src/animetta_qwen_tts/ src/animetta_qwen_tts/" in dockerfile


def test_production_compose_uses_remote_qwen_service_and_health_dependency() -> None:
    compose = yaml.safe_load(_text("docker-compose.yml"))["services"]
    app = compose["animetta"]
    qwen = compose["qwen-tts"]

    assert app["build"]["dockerfile"] == "Dockerfile"
    assert "ANIMETTA_PROFILE=production" in app["environment"]
    assert "QWEN_TTS_URL=http://qwen-tts:8766" in app["environment"]
    assert app["depends_on"]["qwen-tts"]["condition"] == "service_healthy"
    assert qwen["build"]["dockerfile"] == "Dockerfile.qwen-tts"
    assert qwen["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]
    assert qwen["healthcheck"]["start_period"] == "360s"
    assert app["healthcheck"]["start_period"] == "360s"


def test_production_qwen_codec_budget_is_bounded_for_interactive_latency() -> None:
    manifest = yaml.safe_load(_text("config/animetta.yaml"))
    budget = manifest["providers"]["tts"]["qwen-alice"]["worker"]["max_new_tokens"]

    assert budget == 48


def test_cpu_and_core_compose_choose_only_supported_profiles() -> None:
    cpu = yaml.safe_load(_text("docker-compose.cpu.yml"))["services"]
    core = yaml.safe_load(_text("docker-compose.core.yml"))["services"]

    assert set(cpu) == {"animetta"}
    assert "ANIMETTA_PROFILE=${ANIMETTA_PROFILE:-smoke}" in cpu["animetta"]["environment"]
    assert cpu["animetta"]["build"]["dockerfile"] == "Dockerfile"
    assert "ANIMETTA_PROFILE=test" in core["animetta"]["environment"]
    assert core["animetta"]["build"]["dockerfile"] == "Dockerfile"


def test_compose_services_inject_only_explicit_least_privilege_environment() -> None:
    production = yaml.safe_load(_text("docker-compose.yml"))["services"]
    cpu = yaml.safe_load(_text("docker-compose.cpu.yml"))["services"]
    core = yaml.safe_load(_text("docker-compose.core.yml"))["services"]

    for service in (*production.values(), *cpu.values(), *core.values()):
        assert "env_file" not in service

    assert set(cpu["animetta"]["environment"]) == {
        "ANIMETTA_PROFILE=${ANIMETTA_PROFILE:-smoke}",
        "ANIMETTA_HOST=0.0.0.0",
        "ANIMETTA_PORT=12394",
        "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}",
        "MIMO_API_KEY=${MIMO_API_KEY:-}",
    }
    assert not any(
        item.startswith(("DEEPSEEK_API_KEY=", "MIMO_API_KEY="))
        for item in production["qwen-tts"]["environment"]
    )


def test_deployment_descriptors_do_not_select_business_providers() -> None:
    sources = "\n".join(
        _text(path)
        for path in (
            "docker-compose.yml",
            "docker-compose.cpu.yml",
            "docker-compose.core.yml",
            "docker/entrypoint.sh",
            "fly.toml",
            "zeabur.json",
            "frontend/vite.config.ts",
        )
    )

    for selector in LEGACY_SELECTORS:
        assert selector not in sources
    assert "ANIMETTA_PROFILE" in sources


def test_hosted_descriptors_use_core_image_and_production_profile() -> None:
    fly = _text("fly.toml")
    zeabur = json.loads(_text("zeabur.json"))

    assert 'dockerfile = "Dockerfile"' in fly
    assert 'ANIMETTA_PROFILE = "production"' in fly
    backend = zeabur["services"]["backend"]
    assert backend["dockerfile"] == "Dockerfile"
    assert backend["env"]["ANIMETTA_PROFILE"] == "production"


def test_removed_legacy_manifests_and_combined_cuda_image_are_absent() -> None:
    for path in (
        "config/config.yaml",
        "config/config.golden.yaml",
        "config/services.yaml",
        "Dockerfile.cuda",
    ):
        assert not (ROOT / path).exists(), path
