from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import release_runtime_gate as gate
from scripts.release_runtime_gate import (
    ReleaseGateError,
    assert_clean_logs,
    validate_live_soak_evidence,
    validate_playwright_evidence,
    validate_production_readiness,
    validate_release_environment,
)

ROOT = Path(__file__).resolve().parents[2]
TTS_IDENTITY = {
    "type": "dashscope",
    "provider": "dashscope",
    "model": "qwen3-tts-instruct-flash-realtime",
    "voice": "Seren",
}


def _readiness() -> dict[str, object]:
    return {
        "ready": True,
        "status": "ready",
        "profile": "production",
        "acceptance_eligible": True,
        "components": {
            "tts": {
                "ready": True,
                "configured": {"name": "dashscope-seren", **TTS_IDENTITY},
                "resolved": dict(TTS_IDENTITY),
            }
        },
    }


def _completed_browser_turn() -> dict[str, object]:
    return {
        "stream": {
            "format": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
            "status": "completed",
            "sequences": [0, 1],
            "chunks": 2,
            "final_sequence": 1,
        },
        "audio": [
            {"rms": 0.12, "ended": True, "stopped": False},
            {"rms": 0.11, "ended": True, "stopped": False},
        ],
        "legacy_audio_events": 0,
    }


def _playwright_evidence() -> dict[str, object]:
    return {
        "status": "passed",
        "context": "fresh",
        "provider_rows_exact": True,
        "turns": {
            "first": _completed_browser_turn(),
            "interrupted": {
                "stop_audio_events": 1,
                "stream": {
                    "stream_id": "interrupt-stream",
                    "status": "cancelled",
                    "chunks": 1,
                    "sequences": [0],
                    "final_sequence": 0,
                },
                "cancel_to_end_ms": 120.0,
                "chunks_after_end": 0,
                "post_terminal_observation_ms": 350.0,
                "audio": [{"rms": 0.1, "ended": False, "stopped": True}],
            },
            "recovery": _completed_browser_turn(),
        },
        "playback": {
            "audio_contexts": 1,
            "initial_buffer_seconds": 0.2,
            "no_overlap": True,
            "nonzero_pcm_lip_sync_input": True,
            "legacy_play_calls": 1,
        },
        "marker_leaks": [],
        "console_errors": [],
        "page_errors": [],
        "request_failures": [],
        "http_errors": [],
    }


def _soak_evidence() -> dict[str, object]:
    return {
        "status": "passed",
        "turns": [{"audio_ready_ms": 900.0} for _ in range(30)],
        "thresholds": {
            "audio_latency": {
                "turn_count": 30,
                "sample_count": 30,
                "p50_ms": 900.0,
                "p95_ms": 1400.0,
                "complete": True,
                "passed": True,
            }
        },
        "decisions": {
            "turn_count": True,
            "disconnects": True,
            "audio_latency_complete": True,
            "audio_p50": True,
            "audio_p95": True,
        },
    }


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


def test_release_environment_requires_dashscope_and_persistent_rollback_mounts(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "hf"
    audio = tmp_path / "alice.wav"
    cache.mkdir()
    audio.write_bytes(b"RIFF")
    environment = {
        "DASHSCOPE_API_KEY": "dashscope-secret",
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "MIMO_API_KEY": "mimo-secret",
        "QWEN_TTS_API_KEY": "qwen-secret",
        "HF_CACHE_DIR": str(cache),
        "ALICE_REF_AUDIO": str(audio),
    }

    assert validate_release_environment(environment) == tuple(sorted(environment))

    environment["DASHSCOPE_API_KEY"] = ""
    with pytest.raises(ReleaseGateError, match="DASHSCOPE_API_KEY"):
        validate_release_environment(environment)


def test_release_validates_exact_dashscope_seren_identity() -> None:
    readiness = _readiness()

    validate_production_readiness(readiness)

    readiness["components"]["tts"]["resolved"]["voice"] = "Vivian"  # type: ignore[index]
    with pytest.raises(ReleaseGateError, match="DashScope/Seren"):
        validate_production_readiness(readiness)


def test_release_validates_fresh_streaming_browser_evidence() -> None:
    evidence = _playwright_evidence()

    validate_playwright_evidence(evidence)

    evidence["turns"]["recovery"]["stream"]["sequences"] = [1, 0]  # type: ignore[index]
    with pytest.raises(ReleaseGateError, match="Playwright"):
        validate_playwright_evidence(evidence)


def test_release_requires_prompt_cancelled_terminal_stream_before_recovery() -> None:
    evidence = _playwright_evidence()
    evidence["turns"]["interrupted"]["stream"]["status"] = "completed"  # type: ignore[index]

    with pytest.raises(ReleaseGateError, match="Playwright"):
        validate_playwright_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chunks_after_end", 1),
        ("post_terminal_observation_ms", 100.0),
    ],
)
def test_release_requires_quiet_observation_after_cancelled_terminal(
    field: str,
    value: int | float,
) -> None:
    evidence = _playwright_evidence()
    evidence["turns"]["interrupted"][field] = value  # type: ignore[index]

    with pytest.raises(ReleaseGateError, match="Playwright"):
        validate_playwright_evidence(evidence)


def test_release_requires_thirty_complete_turns_and_latency_budget() -> None:
    evidence = _soak_evidence()

    validate_live_soak_evidence(evidence)

    evidence["thresholds"]["audio_latency"]["p95_ms"] = 5001.0  # type: ignore[index]
    with pytest.raises(ReleaseGateError, match="Thirty-turn"):
        validate_live_soak_evidence(evidence)


def test_release_soak_reports_media_completion_without_gating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = tmp_path / "golden-soak.json"
    evidence_path.write_text(json.dumps(_soak_evidence()), encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, **_kwargs):
        command = tuple(str(part) for part in argv)
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=f"{evidence_path}\n", stderr="")

    monkeypatch.setattr(gate, "_run", fake_run)

    assert gate._run_live_soak(tmp_path / "evidence") == _soak_evidence()
    command = commands[0]
    media_index = command.index("--media-p95-ms")
    assert command[media_index + 1] == "0"


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


def test_release_gate_preserves_qwen_and_rebuilds_only_animetta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "hf"
    audio = tmp_path / "alice.wav"
    plan = tmp_path / "plan.json"
    cache.mkdir()
    audio.write_bytes(b"RIFF")
    plan.write_text("{}\n", encoding="utf-8")
    for name, value in {
        "DASHSCOPE_API_KEY": "dashscope-secret",
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "MIMO_API_KEY": "mimo-secret",
        "QWEN_TTS_API_KEY": "qwen-secret",
        "HF_CACHE_DIR": str(cache),
        "ALICE_REF_AUDIO": str(audio),
    }.items():
        monkeypatch.setenv(name, value)

    commands: list[tuple[str, ...]] = []

    def fake_run(argv, **_kwargs):
        command = tuple(str(part) for part in argv)
        commands.append(command)
        if "ps" in command and "qwen-tts" in command:
            stdout = "stable-qwen-container\n"
        elif "inspect" in command:
            stdout = json.dumps(
                [
                    {
                        "Id": "stable-qwen-container",
                        "Image": "sha256:qwen-image",
                        "State": {"StartedAt": "2026-07-16T00:00:00Z"},
                        "RestartCount": 0,
                    }
                ]
            )
        elif "logs" in command:
            stdout = "all services ready\nerror_count=0\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def fake_wait(_url, _predicate, *, description, **_kwargs):
        if description == "Animetta health":
            return {"status": "ok"}
        return _readiness()

    monkeypatch.setattr(gate, "_run", fake_run)
    monkeypatch.setattr(gate, "_wait_json", fake_wait)
    monkeypatch.setattr(
        gate,
        "_preflight_qwen",
        lambda **_kwargs: {"status": "passed", "identity": {"ready": True}},
    )
    monkeypatch.setattr(gate, "_frontend_probe", lambda _url: {"status": 200, "bytes": 12})
    monkeypatch.setattr(gate, "_run_live_soak", lambda _path: _soak_evidence())
    monkeypatch.setattr(gate, "_run_playwright", lambda _path: _playwright_evidence())

    evidence = gate.run_release_gate(
        plan=plan,
        compose_file=tmp_path / "docker-compose.yml",
        qwen_compose_file=tmp_path / "docker-compose.qwen.yml",
        evidence_root=tmp_path / "evidence",
        attempts=2,
        interval_seconds=0,
    )

    flattened = [" ".join(command) for command in commands]
    assert evidence["status"] == "passed"
    assert evidence["readiness"]["components"]["tts"]["resolved"] == TTS_IDENTITY
    assert evidence["persistent_qwen"]["preserved"] is True
    assert evidence["persistent_qwen"]["before"] == evidence["persistent_qwen"]["after"]
    assert evidence["persistent_qwen"]["build_actions"] == 0
    assert evidence["persistent_qwen"]["recreate_actions"] == 0
    assert any("runtime_lifecycle.py qwen-up" in command for command in flattened)
    assert any("runtime_lifecycle.py anima-down" in command for command in flattened)
    assert any("runtime_lifecycle.py anima-up" in command for command in flattened)
    assert not any("qwen-deploy" in command for command in flattened)
    assert not any("qwen-build" in command for command in flattened)
    assert not any("qwen-stop" in command for command in flattened)
    assert not any("qwen-destroy" in command for command in flattened)
    assert not any("--force-recreate" in command for command in flattened)
