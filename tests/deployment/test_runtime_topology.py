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


def _compose(path: str) -> dict:
    payload = yaml.safe_load(_text(path))
    assert isinstance(payload, dict)
    return payload


def _make_target(name: str) -> str:
    lines = _text("Makefile").splitlines()
    start = lines.index(f"{name}:")
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(("\t", " ")):
            break
        body.append(line)
    return "\n".join(body)


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


def test_production_compose_owns_only_animetta_and_joins_external_inference_network() -> None:
    compose = _compose("docker-compose.yml")
    assert set(compose["services"]) == {"animetta"}
    app = compose["services"]["animetta"]
    assert app["build"]["dockerfile"] == "Dockerfile"
    assert "ANIMETTA_PROFILE=production" in app["environment"]
    assert "QWEN_TTS_URL=http://qwen-tts:8766" in app["environment"]
    assert "depends_on" not in app
    assert app["networks"] == ["inference"]
    assert compose["networks"]["inference"] == {
        "external": True,
        "name": "animetta-inference",
    }
    assert app["healthcheck"]["start_period"] == "360s"
def test_qwen_compose_owns_persistent_single_model_gpu_worker() -> None:
    compose = _compose("docker-compose.qwen.yml")
    assert compose["name"] == "animetta-qwen"
    assert set(compose["services"]) == {"qwen-tts"}
    qwen = compose["services"]["qwen-tts"]

    assert qwen["build"]["dockerfile"] == "Dockerfile.qwen-tts"
    assert qwen["image"] == "animetta/qwen-tts:local"
    assert qwen["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]
    assert qwen["healthcheck"]["start_period"] == "360s"
    assert qwen["restart"] == "unless-stopped"
    assert qwen["ports"] == ["127.0.0.1:8766:8766"]
    assert qwen["networks"] == ["inference"]
    assert compose["networks"]["inference"]["name"] == "animetta-inference"
    assert compose["networks"]["inference"].get("external") is not True
    assert "${HF_CACHE_DIR:?" in "\n".join(qwen["volumes"])
    assert "${ALICE_REF_AUDIO:?" in "\n".join(qwen["volumes"])


def test_production_qwen_uses_distinct_generation_and_warmup_budgets() -> None:
    manifest = yaml.safe_load(_text("config/animetta.yaml"))
    qwen = manifest["providers"]["tts"]["qwen-alice"]
    worker = qwen["worker"]
    production = manifest["profiles"]["production"]

    assert worker["max_new_tokens"] == 512
    assert worker["warmup_max_new_tokens"] == 48
    assert worker["temperature"] == 0.9
    assert worker["top_p"] == 1.0
    assert qwen["timeout_seconds"] == 120.0
    assert production["runtime"]["tts_timeout_seconds"] == 120.0


def test_cpu_and_core_compose_choose_only_supported_profiles() -> None:
    cpu = yaml.safe_load(_text("docker-compose.cpu.yml"))["services"]
    core = yaml.safe_load(_text("docker-compose.core.yml"))["services"]

    assert set(cpu) == {"animetta"}
    assert "ANIMETTA_PROFILE=${ANIMETTA_PROFILE:-smoke}" in cpu["animetta"]["environment"]
    assert cpu["animetta"]["build"]["dockerfile"] == "Dockerfile"
    assert "ANIMETTA_PROFILE=test" in core["animetta"]["environment"]
    assert core["animetta"]["build"]["dockerfile"] == "Dockerfile"


def test_compose_services_inject_only_explicit_least_privilege_environment() -> None:
    production = _compose("docker-compose.yml")["services"]
    qwen = _compose("docker-compose.qwen.yml")["services"]
    cpu = _compose("docker-compose.cpu.yml")["services"]
    core = _compose("docker-compose.core.yml")["services"]

    for service in (*production.values(), *qwen.values(), *cpu.values(), *core.values()):
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
        for item in qwen["qwen-tts"]["environment"]
    )


def test_deployment_descriptors_do_not_select_business_providers() -> None:
    sources = "\n".join(
        _text(path)
        for path in (
            "docker-compose.yml",
            "docker-compose.qwen.yml",
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


def test_make_targets_delegate_to_cross_platform_lifecycle_entrypoint() -> None:
    target = _make_target("qwen-up")

    assert "scripts/runtime_lifecycle.py qwen-up" in target
    assert " build" not in target
    assert "--build" not in target
    for operation in (
        "qwen-build",
        "qwen-deploy",
        "qwen-stop",
        "qwen-destroy",
        "anima-up",
        "anima-down",
    ):
        assert f"scripts/runtime_lifecycle.py {operation}" in _make_target(operation)


def test_qwen_build_and_deploy_are_explicit_targets() -> None:
    build = _make_target("qwen-build")
    deploy = _make_target("qwen-deploy")

    assert "runtime_lifecycle.py qwen-build" in build
    assert "runtime_lifecycle.py qwen-deploy" in deploy


def test_animetta_lifecycle_targets_never_reference_qwen_compose() -> None:
    up = _make_target("anima-up")
    down = _make_target("anima-down")

    assert "docker-compose.qwen.yml" not in up
    assert "docker-compose.qwen.yml" not in down
    assert "qwen-tts" not in up
    assert "qwen-tts" not in down
    assert "runtime_lifecycle.py anima-up" in up
    assert "runtime_lifecycle.py anima-down" in down


def test_qwen_stop_preserves_container_and_destroy_is_explicitly_destructive() -> None:
    stop = _make_target("qwen-stop")
    destroy = _make_target("qwen-destroy")

    assert "runtime_lifecycle.py qwen-stop" in stop
    assert " down" not in stop
    assert " rm" not in stop
    assert "runtime_lifecycle.py qwen-destroy" in destroy
    assert "--volumes" not in destroy
    assert "--rmi" not in destroy


def test_qwen_deploy_waits_for_readiness_and_animetta_preflights_before_build() -> None:
    lifecycle = _text("scripts/runtime_lifecycle.py")

    assert 'operation == "qwen-deploy"' in lifecycle
    assert "_preflight(wait=True)" in lifecycle
    assert 'operation == "anima-up"' in lifecycle
    assert lifecycle.index("_run(_preflight(wait=False))") < lifecycle.index(
        '_run(["docker", "compose", "build", "animetta"])'
    )


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
