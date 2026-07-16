from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts import release_runtime_gate as gate
from scripts.release_runtime_gate import (
    ReleaseGateError,
    assert_clean_logs,
    validate_playwright_evidence,
    validate_production_readiness,
    validate_release_environment,
    validate_smoke_evidence,
)
from scripts.smoke_qwen_alice import build_evidence

ROOT = Path(__file__).resolve().parents[2]
RESOLVED_IDENTITY = {
    "provider": "qwen3",
    "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "voice": "alice",
    "revision": "5d83992436eae1d760afd27aff78a71d676296fc",
}


def test_preload_counter_uses_the_qwen_runtime_log_event() -> None:
    logs = (
        "Qwen3-TTS model load started\n"
        "Qwen3-TTS model loaded successfully\n"
        "Qwen3-TTS model load started\n"
    )

    assert gate._preload_event_count(logs) == 2


def test_release_gate_script_entrypoint_can_import_qwen_preflight() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/release_runtime_gate.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert completed.returncode == 0, completed.stderr
    assert "--qwen-compose-file" in completed.stdout


def test_release_environment_requires_secrets_and_existing_model_mounts(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "hf"
    audio = tmp_path / "alice.wav"
    cache.mkdir()
    audio.write_bytes(b"RIFF")
    environment = {
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "MIMO_API_KEY": "mimo-secret",
        "QWEN_TTS_API_KEY": "qwen-secret",
        "HF_CACHE_DIR": str(cache),
        "ALICE_REF_AUDIO": str(audio),
    }

    assert validate_release_environment(environment) == tuple(sorted(environment))

    environment["MIMO_API_KEY"] = ""
    with pytest.raises(ReleaseGateError, match="MIMO_API_KEY"):
        validate_release_environment(environment)


def test_alice_smoke_requires_exact_resolved_remote_identity_and_wav() -> None:
    evidence = {
        "ok": True,
        "audio_bytes": 4096,
        "volume_samples": 4,
        "volume_nonzero": 4,
        "provider": {
            "type": "remote",
            "provider": "qwen3",
            "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "voice": "alice",
            "resolved": RESOLVED_IDENTITY,
        },
    }

    validate_smoke_evidence(evidence)

    evidence["provider"]["voice"] = "default"
    with pytest.raises(ReleaseGateError, match="identity"):
        validate_smoke_evidence(evidence)


def test_real_alice_smoke_builder_schema_is_accepted() -> None:
    provider = SimpleNamespace(
        provider="qwen3",
        model="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        voice="alice",
        resolved_identity=RESOLVED_IDENTITY,
    )
    evidence = build_evidence(b"not-empty-audio", provider, "task-id")
    evidence.update(ok=True, audio_bytes=4096, volume_samples=4, volume_nonzero=4)

    validate_smoke_evidence(evidence)


def test_alice_smoke_rejects_silent_wav_evidence() -> None:
    evidence = {
        "ok": True,
        "audio_bytes": 4096,
        "volume_samples": 4,
        "volume_nonzero": 0,
        "provider": {
            "type": "remote",
            "provider": "qwen3",
            "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "voice": "alice",
            "resolved": RESOLVED_IDENTITY,
        },
    }

    with pytest.raises(ReleaseGateError, match="WAV"):
        validate_smoke_evidence(evidence)


def test_release_validates_exact_application_and_browser_evidence() -> None:
    readiness = {
        "ready": True,
        "status": "ready",
        "profile": "production",
        "components": {
            "tts": {
                "ready": True,
                "configured": {
                    "type": "remote",
                    "provider": "qwen3",
                    "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                    "voice": "alice",
                },
                "resolved": RESOLVED_IDENTITY,
            }
        },
    }
    browser = {
        "status": "passed",
        "core_ui": {"passed": True},
        "release_acceptance": {
            "passed": True,
            "provider_rows_exact": True,
            "chinese_turn_complete": True,
            "audio": {
                "play_calls": 1,
                "play_resolved": 1,
                "ended": 1,
                "play_rejected": 0,
            },
        },
    }

    validate_production_readiness(readiness)
    validate_playwright_evidence(browser)

    browser["core_ui"]["passed"] = False
    with pytest.raises(ReleaseGateError, match="Playwright"):
        validate_playwright_evidence(browser)


def test_release_log_gate_rejects_forbidden_levels_but_not_error_counters() -> None:
    assert_clean_logs("requests=12 error_count=0\nall services ready\n")

    with pytest.raises(ReleaseGateError, match="forbidden"):
        assert_clean_logs("2026-07-15 | ERROR | remote provider crashed\n")


def test_failed_command_reports_both_stdout_and_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["probe"],
            1,
            stdout='{"status":"failed","error":"typed busy"}\n',
            stderr="provider import warning\n",
        ),
    )

    with pytest.raises(ReleaseGateError) as exc_info:
        gate._run(["probe"])

    message = str(exc_info.value)
    assert "typed busy" in message
    assert "provider import warning" in message


def test_release_gate_runs_cold_dual_image_startup_outage_and_same_container_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "hf"
    audio = tmp_path / "alice.wav"
    cache.mkdir()
    audio.write_bytes(b"RIFF")
    for name, value in {
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "MIMO_API_KEY": "mimo-secret",
        "QWEN_TTS_API_KEY": "qwen-secret",
        "HF_CACHE_DIR": str(cache),
        "ALICE_REF_AUDIO": str(audio),
    }.items():
        monkeypatch.setenv(name, value)

    smoke = {
        "ok": True,
        "audio_bytes": 4096,
        "volume_samples": 4,
        "volume_nonzero": 4,
        "provider": {
            "type": "remote",
            "provider": "qwen3",
            "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            "voice": "alice",
            "resolved": RESOLVED_IDENTITY,
        },
    }
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, **_kwargs):
        command = tuple(str(part) for part in argv)
        commands.append(command)
        if "docker-build" in command:
            stdout = json.dumps(
                {
                    "status": "passed",
                    "actions": [{"scope_id": "animetta"}, {"scope_id": "qwen-tts"}],
                }
            )
        elif any(part.endswith("smoke_qwen_alice.py") for part in command):
            stdout = json.dumps(smoke)
        elif any(part.endswith("probe_release_turn.py") for part in command):
            expected = command[command.index("--expect") + 1]
            conversation_id = command[command.index("--conversation-id") + 1]
            stdout = json.dumps(
                {
                    "status": "passed",
                    "conversation_id": conversation_id,
                    "safe_output": "安全的中文回复。",
                    "degraded": expected == "degraded",
                    "audio_count": 0 if expected == "degraded" else 1,
                    "degradation_count": 1 if expected == "degraded" else 0,
                    "expression_count": 1,
                    "action_count": 1,
                }
            )
        elif "ps" in command and "qwen-tts" in command:
            stdout = "stable-qwen-container\n"
        elif "ps" in command and "animetta" in command:
            stdout = "stable-animetta-container\n"
        elif "inspect" in command:
            container_id = command[-1]
            stdout = json.dumps(
                [
                    {
                        "Id": container_id,
                        "Image": "sha256:qwen-image",
                        "State": {"StartedAt": "2026-07-16T00:00:00Z"},
                        "RestartCount": 0,
                    }
                ]
            )
        elif "logs" in command:
            stdout = "Qwen3-TTS model load started\nall services ready\nerror_count=0\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def fake_wait(_url, _predicate, *, description, **_kwargs):
        if description == "remote TTS outage":
            return {"ready": False, "status": "not_ready"}
        if description == "Animetta health":
            return {"status": "ok"}
        return {
            "ready": True,
            "status": "ready",
            "profile": "production",
            "components": {
                "tts": {
                    "ready": True,
                    "configured": {
                        "type": "remote",
                        "provider": "qwen3",
                        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                        "voice": "alice",
                    },
                    "resolved": RESOLVED_IDENTITY,
                }
            },
        }

    monkeypatch.setattr(gate, "_run", fake_run)
    monkeypatch.setattr(gate, "_wait_json", fake_wait)
    monkeypatch.setattr(
        gate,
        "_preflight_qwen",
        lambda **_kwargs: {"status": "passed", "identity": {"ready": True, **RESOLVED_IDENTITY}},
    )
    monkeypatch.setattr(gate, "_frontend_probe", lambda _url: {"status": 200, "bytes": 12})
    monkeypatch.setattr(
        gate,
        "_run_playwright",
        lambda _path: {
            "status": "passed",
            "core_ui": {"passed": True},
            "release_acceptance": {
                "passed": True,
                "provider_rows_exact": True,
                "chinese_turn_complete": True,
                "audio": {
                    "play_calls": 1,
                    "play_resolved": 1,
                    "ended": 1,
                    "play_rejected": 0,
                },
            },
        },
    )

    evidence = gate.run_release_gate(
        plan=tmp_path / "plan.json",
        compose_file=tmp_path / "docker-compose.yml",
        qwen_compose_file=tmp_path / "docker-compose.qwen.yml",
        evidence_root=tmp_path / "evidence",
        attempts=2,
        interval_seconds=0,
    )

    flattened = [" ".join(command) for command in commands]
    assert evidence["status"] == "passed"
    assert evidence["same_container_recovery"] is True
    assert sum("smoke_qwen_alice.py" in command for command in flattened) == 3
    assert sum("probe_release_turn.py" in command for command in flattened) == 2
    probe_commands = [
        command
        for command in commands
        if any(part.endswith("probe_release_turn.py") for part in command)
    ]
    conversation_ids = {
        command[command.index("--conversation-id") + 1] for command in probe_commands
    }
    assert len(conversation_ids) == 1
    assert str(UUID(next(iter(conversation_ids)))) == next(iter(conversation_ids))
    assert any("down --remove-orphans" in command for command in flattened)
    assert any("docker-build" in command and "--no-cache" in command for command in flattened)
    assert not any(
        "docker-build" in command and "--compose-file" in command for command in flattened
    )
    assert any(
        "docker-compose.qwen.yml up -d --no-build --force-recreate qwen-tts" in command
        for command in flattened
    )
    assert any("docker-compose.yml up -d --no-build animetta" in command for command in flattened)
    assert any("stop qwen-tts" in command for command in flattened)
    assert any("start qwen-tts" in command for command in flattened)
    assert all(
        "docker-compose.qwen.yml" in command
        for command in flattened
        if " qwen-tts" in command and (" stop " in command or " start " in command)
    )
    assert evidence["qwen_compose_file"].endswith("docker-compose.qwen.yml")
    assert evidence["main_compose_file"].endswith("docker-compose.yml")
    assert evidence["persistent_qwen"]["preserved"] is True
    assert evidence["persistent_qwen"]["before"] == evidence["persistent_qwen"]["after"]
    assert evidence["persistent_qwen"]["preload_events_before"] == 1
    assert evidence["persistent_qwen"]["preload_events_after"] == 1
    assert evidence["persistent_qwen"]["build_actions"] == 0
    assert len(evidence["persistent_qwen"]["noop_up_seconds"]) == 2
    assert max(evidence["persistent_qwen"]["noop_up_seconds"]) <= 5
    assert sum("--no-recreate qwen-tts" in command for command in flattened) == 2
