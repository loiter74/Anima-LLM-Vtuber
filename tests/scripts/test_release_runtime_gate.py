from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import release_runtime_gate as gate
from scripts.release_runtime_gate import (
    ReleaseGateError,
    assert_clean_logs,
    validate_conversation_continuity_evidence,
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
                "configured": {
                    "name": "dashscope-local-failover",
                    "type": "failover",
                    "provider": "failover",
                    "model": None,
                    "voice": None,
                },
                "resolved": {
                    "type": "failover",
                    "provider": "failover",
                    "model": None,
                    "voice": None,
                },
                "primary": {
                    "ready": False,
                    "error_category": "billing",
                    "identity": dict(TTS_IDENTITY),
                },
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


def _continuity_evidence() -> dict[str, object]:
    transitions = [
        ("developer_seed", 0, 1, True, "developer", "developer_console"),
        ("replay_probe", 1, 1, False, "viewer", "bilibili:danmaku"),
        ("viewer_reply", 1, 2, True, "viewer", "bilibili:danmaku"),
        ("developer_followup", 2, 3, True, "developer", "developer_console"),
    ]
    return {
        "schema_version": 1,
        "status": "passed",
        "run_id": "continuity-run",
        "provider_real": True,
        "socket_recreated": True,
        "steps": [
            {
                "step_id": step_id,
                "trace_id": f"trace-{index}",
                "scope_kind": "livestream",
                "window_before": before,
                "window_after": after,
                "committed": committed,
                "actor_role": actor_role,
                "source": source,
                "public_fact_recalled": True if index >= 2 else None,
                "private_marker_absent": True if index >= 2 else None,
            }
            for index, (step_id, before, after, committed, actor_role, source) in enumerate(
                transitions
            )
        ],
        "error_codes": [],
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
    assert "--qwen-compose-file" not in completed.stdout


def test_release_environment_requires_provider_credentials() -> None:
    environment = {
        "DASHSCOPE_API_KEY": "dashscope-secret",
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "MIMO_API_KEY": "mimo-secret",
        "QWEN_TTS_API_KEY": "qwen-secret",
    }

    assert validate_release_environment(environment) == tuple(sorted(environment))

    environment["DASHSCOPE_API_KEY"] = ""
    with pytest.raises(ReleaseGateError, match="DASHSCOPE_API_KEY"):
        validate_release_environment(environment)


def test_release_validates_exact_dashscope_seren_identity() -> None:
    readiness = _readiness()

    validate_production_readiness(readiness)

    readiness["components"]["tts"]["primary"]["identity"]["voice"] = "Vivian"  # type: ignore[index]
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


def test_release_requires_content_free_conversation_continuity_evidence() -> None:
    evidence = _continuity_evidence()

    validate_conversation_continuity_evidence(evidence)

    evidence["steps"][1]["committed"] = True  # type: ignore[index]
    with pytest.raises(ReleaseGateError, match="transition"):
        validate_conversation_continuity_evidence(evidence)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update(status="failed"), "incomplete"),
        (lambda value: value.update(provider_real=False), "incomplete"),
        (lambda value: value.update(socket_recreated=False), "incomplete"),
        (lambda value: value.pop("run_id"), "incomplete"),
        (
            lambda value: value["steps"][2].update(private_marker_absent=False),
            "private_marker_leaked",
        ),
        (lambda value: value["steps"][0].pop("source"), "fields"),
        (lambda value: value["steps"][0].update(response_text="forbidden"), "fields"),
    ],
)
def test_release_continuity_evidence_fails_closed(mutation, match: str) -> None:
    evidence = _continuity_evidence()
    mutation(evidence)

    with pytest.raises(ReleaseGateError, match=match):
        validate_conversation_continuity_evidence(evidence)


def test_release_runs_conversation_canary_and_reads_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(argv, **_kwargs):
        command = tuple(str(part) for part in argv)
        commands.append(command)
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_continuity_evidence()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout=f"{output}\n", stderr="")

    monkeypatch.setattr(gate, "_run", fake_run)

    assert gate._run_conversation_continuity(tmp_path) == _continuity_evidence()
    assert "scripts/conversation_continuity_canary.py" in commands[0]


def test_release_soak_reports_media_completion_without_gating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = tmp_path / "golden-soak.json"
    evidence_path.write_text(json.dumps(_soak_evidence()), encoding="utf-8")
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []
    monkeypatch.setenv("PYTHONPATH", "existing-path")

    def fake_run(argv, **kwargs):
        command = tuple(str(part) for part in argv)
        commands.append(command)
        environments.append(dict(kwargs["environment"]))
        return subprocess.CompletedProcess(command, 0, stdout=f"{evidence_path}\n", stderr="")

    monkeypatch.setattr(gate, "_run", fake_run)

    assert gate._run_live_soak(tmp_path / "evidence") == _soak_evidence()
    command = commands[0]
    media_index = command.index("--media-p95-ms")
    assert command[media_index + 1] == "0"
    assert environments[0]["PYTHONPATH"].split(os.pathsep) == [
        str((gate.ROOT / "src").resolve()),
        "existing-path",
    ]


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


def test_release_gate_uses_host_qwen_and_rebuilds_only_animetta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}\n", encoding="utf-8")
    for name, value in {
        "DASHSCOPE_API_KEY": "dashscope-secret",
        "DEEPSEEK_API_KEY": "deepseek-secret",
        "MIMO_API_KEY": "mimo-secret",
        "QWEN_TTS_API_KEY": "qwen-secret",
    }.items():
        monkeypatch.setenv(name, value)

    commands: list[tuple[str, ...]] = []

    def fake_run(argv, **_kwargs):
        command = tuple(str(part) for part in argv)
        commands.append(command)
        stdout = "all services ready\nerror_count=0\n" if "logs" in command else ""
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
    monkeypatch.setattr(
        gate,
        "_run_conversation_continuity",
        lambda _path: _continuity_evidence(),
    )

    evidence = gate.run_release_gate(
        plan=plan,
        compose_file=tmp_path / "docker-compose.yml",
        evidence_root=tmp_path / "evidence",
        attempts=2,
        interval_seconds=0,
    )

    flattened = [" ".join(command) for command in commands]
    assert evidence["status"] == "passed"
    assert evidence["schema_version"] == 3
    assert evidence["conversation_continuity"] == _continuity_evidence()
    assert evidence["readiness"]["components"]["tts"]["primary"]["identity"] == TTS_IDENTITY
    assert evidence["host_qwen"] == {"status": "passed", "identity": {"ready": True}}
    assert any("runtime_lifecycle.py host-tts-up" in command for command in flattened)
    assert any("runtime_lifecycle.py anima-down" in command for command in flattened)
    assert any("runtime_lifecycle.py anima-up" in command for command in flattened)
    assert not any("docker-compose.qwen.yml" in command for command in flattened)
    assert not any("--force-recreate" in command for command in flattened)
