from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gpu_compose_selects_fail_closed_golden_profile() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "ANIMETTA_CONFIG=/app/config/config.golden.yaml" in compose
    assert "ANIMETTA_LLM=deepseek" in compose
    assert "ANIMETTA_TTS=alice_vc" in compose
    assert "ANIMETTA_ASR=mock" in compose
    assert "ANIMETTA_VAD=silero" in compose
    assert "ANIMETTA_TTS=${ANIMETTA_TTS:-mock}" not in compose
    assert "D:/huggingface_cache" not in compose
    assert "${HF_CACHE_DIR:?" in compose
    assert "${ALICE_REF_AUDIO:?" in compose
    assert "./config:/app/config:ro" not in compose


def test_gpu_container_uses_readiness_not_liveness_for_health() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.cuda").read_text(encoding="utf-8")
    nginx = (ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")

    assert "http://localhost:80/ready" in compose
    assert "http://localhost:80/ready" in dockerfile
    assert "location = /ready" in nginx
    assert "location = /health" in nginx


def test_gpu_entrypoint_runs_static_preflight_before_processes() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    preflight = entrypoint.index("scripts/baseline_golden_path.py")
    nginx = entrypoint.index("nginx -t")
    backend = entrypoint.index("python -m animetta.core.socketio_server")
    assert preflight < nginx < backend


def test_gpu_image_precreates_read_only_alice_mountpoint() -> None:
    dockerfile = (ROOT / "Dockerfile.cuda").read_text(encoding="utf-8")

    assert "ffmpeg nginx curl sox build-essential" in dockerfile
    assert "mkdir -p /app/config/personas/voices" in dockerfile
    assert "touch /app/config/personas/voices/alice_ref.wav" in dockerfile
