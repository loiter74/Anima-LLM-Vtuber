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

    assert "requirements.txt" in dockerfile
    assert "requirements-core.txt" not in dockerfile
    assert "requirements-dev.txt" not in dockerfile
    assert "requirements-local-ai.txt" not in dockerfile
    assert "requirements-qwen-tts.txt" not in dockerfile
    assert "Dockerfile.cuda" not in dockerfile
    assert "https://deb.debian.org" in dockerfile
    assert "Acquire::Retries=5" in dockerfile


def test_main_image_does_not_copy_removed_stats_placeholder() -> None:
    dockerfile = _text("Dockerfile")

    assert "frontend/stats" not in dockerfile


def test_build_context_excludes_reference_audio_from_all_images() -> None:
    dockerignore = _text(".dockerignore")

    assert "config/personas/voices/" in dockerignore.splitlines()


def test_build_context_excludes_local_frontend_package_cache() -> None:
    dockerignore = _text(".dockerignore")

    assert "frontend/.pnpm-store/" in dockerignore.splitlines()


def test_production_compose_owns_only_animetta_and_targets_host_qwen() -> None:
    compose = _compose("docker-compose.yml")
    assert set(compose["services"]) == {"animetta"}
    app = compose["services"]["animetta"]
    assert app["build"]["dockerfile"] == "Dockerfile"
    assert "ANIMETTA_PROFILE=${ANIMETTA_PROFILE:-production}" in app["environment"]
    assert "DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:-}" in app["environment"]
    assert "QWEN_HOST_TTS_URL=http://host.docker.internal:8767" in app["environment"]
    assert "MC_MCP_URL=${MC_MCP_URL:-http://host.docker.internal:8768/mcp}" in app["environment"]
    assert "MC_MCP_AUTH_TOKEN=${MC_MCP_AUTH_TOKEN:-}" in app["environment"]
    assert "depends_on" not in app
    assert "networks" not in app
    assert "networks" not in compose
    assert app["healthcheck"]["start_period"] == "360s"


def test_manifest_has_one_host_qwen_runtime_contract() -> None:
    manifest = yaml.safe_load(_text("config/animetta.yaml"))
    qwen = manifest["providers"]["tts"]["qwen-host"]
    smoke = manifest["profiles"]["smoke"]
    production = manifest["profiles"]["production"]

    assert qwen == manifest["providers"]["tts"]["dashscope-local-failover"]["fallback"]
    assert qwen["contract"] == "host-tts"
    assert qwen["base_url"] == "${QWEN_HOST_TTS_URL}"
    assert set(qwen) == {"type", "contract", "api_key", "base_url"}
    assert smoke["services"]["tts"] == "qwen-host"
    assert smoke["runtime"]["tts_timeout_seconds"] == 120.0
    assert production["services"]["tts"] == "dashscope-local-failover"
    assert production["runtime"]["tts_timeout_seconds"] == 20.0


def test_release_browser_smoke_allows_a_slow_local_qwen_audio_budget() -> None:
    smoke = _text("frontend/smoke-test.mjs")

    assert "PLAYWRIGHT_RELEASE_AUDIO_TIMEOUT_MS" in smoke
    assert "const releaseAudioTimeoutMs" in smoke
    assert "timeout: releaseAudioTimeoutMs" in smoke


def test_release_browser_smoke_observes_audio_end_before_application_cleanup() -> None:
    smoke = _text("frontend/smoke-test.mjs")

    assert "Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'onended')" in smoke
    assert "Object.defineProperty(HTMLMediaElement.prototype, 'onended'" in smoke
    assert "releaseAcceptance.audio.play_calls === 2" in smoke
    assert "releaseAcceptance.audio.play_resolved === 2" in smoke
    assert "releaseAcceptance.audio.ended >= 1" in smoke


def test_animetta_compose_http_port_is_overridable_for_isolated_validation() -> None:
    app = _compose("docker-compose.yml")["services"]["animetta"]
    assert app["ports"][0] == "${ANIMETTA_HTTP_PORT:-80}:80"


def test_production_redirects_legacy_live_stream_to_canonical_obs_surface() -> None:
    nginx = _text("docker/nginx.conf")

    assert "location = /live-stream" in nginx
    assert "absolute_redirect off;" in nginx
    assert "return 308 /live.html$is_args$args;" in nginx


def test_compose_services_inject_only_explicit_least_privilege_environment() -> None:
    services = _compose("docker-compose.yml")["services"]
    app = services["animetta"]

    assert "env_file" not in app
    assert set(app["environment"]) == {
        "ANIMETTA_PROFILE=${ANIMETTA_PROFILE:-production}",
        "ANIMETTA_HOST=0.0.0.0",
        "ANIMETTA_PORT=12394",
        "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}",
        "DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:-}",
        "MIMO_API_KEY=${MIMO_API_KEY:-}",
        "QWEN_TTS_API_KEY=${QWEN_TTS_API_KEY:-}",
        "QWEN_HOST_TTS_URL=http://host.docker.internal:8767",
        "MC_MCP_URL=${MC_MCP_URL:-http://host.docker.internal:8768/mcp}",
        "MC_MCP_AUTH_TOKEN=${MC_MCP_AUTH_TOKEN:-}",
    }


def test_deployment_descriptors_do_not_select_business_providers() -> None:
    sources = "\n".join(
        _text(path)
        for path in (
            "docker-compose.yml",
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
    target = _make_target("host-tts-up")

    assert "scripts/runtime_lifecycle.py host-tts-up" in target
    assert " build" not in target
    assert "--build" not in target
    for operation in (
        "host-tts-status",
        "host-tts-stop",
        "anima-up",
        "anima-down",
    ):
        assert f"scripts/runtime_lifecycle.py {operation}" in _make_target(operation)


def test_animetta_lifecycle_targets_never_reference_qwen_compose() -> None:
    up = _make_target("anima-up")
    down = _make_target("anima-down")

    assert "docker-compose.qwen.yml" not in up
    assert "docker-compose.qwen.yml" not in down
    assert "qwen-tts" not in up
    assert "qwen-tts" not in down
    assert "runtime_lifecycle.py anima-up" in up
    assert "runtime_lifecycle.py anima-down" in down


def test_animetta_starts_and_preflights_host_tts_before_build() -> None:
    lifecycle = _text("scripts/runtime_lifecycle.py")

    assert 'operation == "anima-up"' in lifecycle
    assert lifecycle.index("_host_tts_up(best_effort=False)") < lifecycle.index(
        "_run(_preflight(wait=False))"
    )
    assert lifecycle.index("_run(_preflight(wait=False))") < lifecycle.index(
        '["docker", "compose", "build", "animetta"]'
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
        "Dockerfile.qwen-tts",
        "docker-compose.qwen.yml",
        "docker-compose.cpu.yml",
        "docker-compose.core.yml",
        "docker-compose.selftest.yml",
        "requirements-qwen-tts.txt",
        "requirements-core.txt",
        "requirements-host-tts.txt",
        "requirements-livestream-eval.txt",
    ):
        assert not (ROOT / path).exists(), path
