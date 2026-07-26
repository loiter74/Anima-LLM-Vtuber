#!/usr/bin/env python3
"""Production Docker release gate for DashScope streaming TTS."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.qwen_preflight import load_expected_settings as load_qwen_expected_settings
from scripts.qwen_preflight import run_preflight as run_qwen_preflight

REQUIRED_ENVIRONMENT = (
    "ALICE_REF_AUDIO",
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "HF_CACHE_DIR",
    "MIMO_API_KEY",
    "QWEN_TTS_API_KEY",
)
_FORBIDDEN_LOG_PATTERN = re.compile(
    r"Traceback|(?:^|[|\s])(?:ERROR|CRITICAL|FATAL)(?:[|\s:]|$)",
    re.MULTILINE,
)
_PRODUCTION_TTS_IDENTITY = {
    "type": "dashscope",
    "provider": "dashscope",
    "model": "qwen3-tts-instruct-flash-realtime",
    "voice": "Seren",
}
_PRODUCTION_COMPOSITE_TTS_IDENTITY = {
    "type": "failover",
    "provider": "failover",
}


class ReleaseGateError(RuntimeError):
    """Release evidence is incomplete or unsafe."""


def validate_release_environment(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Validate production secrets and persistent rollback mounts."""
    missing = [name for name in REQUIRED_ENVIRONMENT if not environment.get(name, "").strip()]
    if missing:
        raise ReleaseGateError("Missing release environment fields: " + ", ".join(sorted(missing)))
    for name in ("HF_CACHE_DIR", "ALICE_REF_AUDIO"):
        if not Path(environment[name]).exists():
            raise ReleaseGateError(f"Release mount path does not exist: {name}")
    return tuple(sorted(REQUIRED_ENVIRONMENT))


def validate_production_readiness(payload: Mapping[str, Any]) -> None:
    """Require the failover route and exact DashScope/Seren primary identity."""
    components = payload.get("components")
    tts = components.get("tts") if isinstance(components, Mapping) else None
    configured = tts.get("configured") if isinstance(tts, Mapping) else None
    resolved = tts.get("resolved") if isinstance(tts, Mapping) else None
    primary = tts.get("primary") if isinstance(tts, Mapping) else None
    primary_identity = primary.get("identity") if isinstance(primary, Mapping) else None
    if not (
        _ready(payload)
        and payload.get("profile") == "production"
        and payload.get("acceptance_eligible") is True
        and isinstance(tts, Mapping)
        and tts.get("ready") is True
        and isinstance(configured, Mapping)
        and all(
            configured.get(key) == value
            for key, value in _PRODUCTION_COMPOSITE_TTS_IDENTITY.items()
        )
        and isinstance(resolved, Mapping)
        and all(
            resolved.get(key) == value for key, value in _PRODUCTION_COMPOSITE_TTS_IDENTITY.items()
        )
        and isinstance(primary_identity, Mapping)
        and all(
            primary_identity.get(key) == value for key, value in _PRODUCTION_TTS_IDENTITY.items()
        )
    ):
        raise ReleaseGateError(
            "Application readiness lacks exact production DashScope/Seren identity"
        )


def _completed_browser_turn(turn: Any) -> bool:
    if not isinstance(turn, Mapping):
        return False
    stream = turn.get("stream")
    audio = turn.get("audio")
    if not isinstance(stream, Mapping) or not isinstance(audio, list) or not audio:
        return False
    sequences = stream.get("sequences")
    if not isinstance(sequences, list) or sequences != list(range(len(sequences))):
        return False
    return bool(
        stream.get("format") == "pcm_s16le"
        and stream.get("sample_rate") == 24000
        and stream.get("channels") == 1
        and stream.get("status") == "completed"
        and int(stream.get("chunks", 0)) > 0
        and stream.get("final_sequence") == int(stream.get("chunks", 0)) - 1
        and any(float(entry.get("rms", 0.0)) > 0.001 for entry in audio)
        and all(entry.get("ended") is True and entry.get("stopped") is not True for entry in audio)
        and int(turn.get("legacy_audio_events", 0)) == 0
    )


def validate_playwright_evidence(evidence: Mapping[str, Any]) -> None:
    """Require fresh streamed playback, interruption, recovery, and clean browser state."""
    turns = evidence.get("turns")
    playback = evidence.get("playback")
    interrupted = turns.get("interrupted") if isinstance(turns, Mapping) else None
    interruption_ok = (
        isinstance(interrupted, Mapping) and int(interrupted.get("stop_audio_events", 0)) > 0
    )
    if interruption_ok:
        audio = interrupted.get("audio")
        stream = interrupted.get("stream")
        sequences = stream.get("sequences") if isinstance(stream, Mapping) else None
        chunks = int(stream.get("chunks", 0)) if isinstance(stream, Mapping) else 0
        cancel_to_end_ms = interrupted.get("cancel_to_end_ms")
        observation_ms = interrupted.get("post_terminal_observation_ms")
        interruption_ok = (
            isinstance(audio, list)
            and bool(audio)
            and all(entry.get("stopped") is True or entry.get("ended") is True for entry in audio)
            and isinstance(stream, Mapping)
            and stream.get("status") == "cancelled"
            and isinstance(sequences, list)
            and sequences == list(range(len(sequences)))
            and chunks > 0
            and stream.get("final_sequence") == chunks - 1
            and int(interrupted.get("chunks_after_end", 0)) == 0
            and isinstance(cancel_to_end_ms, (int, float))
            and 0.0 <= float(cancel_to_end_ms) <= 3000.0
            and isinstance(observation_ms, (int, float))
            and float(observation_ms) >= 250.0
        )
    errors = (
        evidence.get("console_errors"),
        evidence.get("page_errors"),
        evidence.get("request_failures"),
        evidence.get("http_errors"),
        evidence.get("marker_leaks"),
    )
    if not (
        evidence.get("status") == "passed"
        and evidence.get("context") == "fresh"
        and evidence.get("provider_rows_exact") is True
        and isinstance(turns, Mapping)
        and _completed_browser_turn(turns.get("first"))
        and _completed_browser_turn(turns.get("recovery"))
        and interruption_ok
        and isinstance(playback, Mapping)
        and playback.get("audio_contexts") == 1
        and playback.get("initial_buffer_seconds") == 0.2
        and playback.get("no_overlap") is True
        and playback.get("nonzero_pcm_lip_sync_input") is True
        and playback.get("legacy_play_calls") == 1
        and all(value == [] for value in errors)
    ):
        raise ReleaseGateError("Fresh Playwright streaming TTS evidence is incomplete")


def validate_live_soak_evidence(evidence: Mapping[str, Any]) -> None:
    """Require 30 complete real turns and the approved first-sound latency budget."""
    turns = evidence.get("turns")
    thresholds = evidence.get("thresholds")
    audio = thresholds.get("audio_latency") if isinstance(thresholds, Mapping) else None
    decisions = evidence.get("decisions")
    if not (
        evidence.get("status") == "passed"
        and isinstance(turns, list)
        and len(turns) >= 30
        and isinstance(audio, Mapping)
        and audio.get("complete") is True
        and audio.get("passed") is True
        and int(audio.get("sample_count", 0)) >= 30
        and float(audio.get("p50_ms", 0.0)) <= 3000.0
        and float(audio.get("p95_ms", 0.0)) <= 5000.0
        and isinstance(decisions, Mapping)
        and all(value for value in decisions.values() if isinstance(value, bool))
    ):
        raise ReleaseGateError("Thirty-turn streaming latency evidence is incomplete")


def assert_clean_logs(logs: str) -> None:
    """Reject traceback and error-level runtime logs without matching metric names."""
    match = _FORBIDDEN_LOG_PATTERN.search(logs)
    if match is not None:
        line = logs[logs.rfind("\n", 0, match.start()) + 1 : logs.find("\n", match.end())]
        raise ReleaseGateError(f"Runtime logs contain a forbidden entry: {line[:240]}")


def _run(
    argv: Sequence[str],
    *,
    cwd: Path = ROOT,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(environment) if environment is not None else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=7200,
    )
    if completed.returncode != 0:
        diagnostic = (
            f"--- stdout ---\n{completed.stdout[-3000:]}\n"
            f"--- stderr ---\n{completed.stderr[-3000:]}"
        )
        raise ReleaseGateError(
            f"Command failed ({completed.returncode}): {' '.join(argv)}\n{diagnostic}"
        )
    return completed


def _compose(compose_file: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file), *args]


def _read_json(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - fixed local URLs only
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
    except (OSError, URLError) as exc:
        raise ReleaseGateError(f"Request failed for {url}: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ReleaseGateError(f"Non-JSON response from {url}") from exc
    if not isinstance(payload, dict):
        raise ReleaseGateError(f"Non-object JSON response from {url}")
    return payload


def _wait_json(
    url: str,
    predicate: Callable[[Mapping[str, Any]], bool],
    *,
    attempts: int,
    interval_seconds: float,
    description: str,
) -> dict[str, Any]:
    last_payload: dict[str, Any] | None = None
    last_error: ReleaseGateError | None = None
    for attempt in range(attempts):
        try:
            last_payload = _read_json(url)
            if predicate(last_payload):
                return last_payload
        except ReleaseGateError as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(interval_seconds)
    detail = last_payload if last_payload is not None else str(last_error)
    raise ReleaseGateError(f"Timed out waiting for {description}: {detail}")


def _frontend_probe(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 - fixed local URL only
            body = response.read()
            status = response.status
    except (HTTPError, OSError, URLError) as exc:
        raise ReleaseGateError(f"Frontend request failed: {exc}") from exc
    if status != 200 or not body:
        raise ReleaseGateError(f"Frontend response is invalid: status={status}")
    return {"status": status, "bytes": len(body)}


def _container_metadata(compose_file: Path, service: str) -> dict[str, Any]:
    container_id = _run(_compose(compose_file, "ps", "-q", service)).stdout.strip()
    if not container_id:
        raise ReleaseGateError(f"No running container found for {service}")
    completed = _run(["docker", "inspect", container_id])
    try:
        current = json.loads(completed.stdout)[0]
        state = current["State"]
        return {
            "container_id": str(current.get("Id", container_id)),
            "image_id": str(current["Image"]),
            "started_at": str(state["StartedAt"]),
            "restart_count": int(current.get("RestartCount", 0)),
        }
    except (json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ReleaseGateError(f"Invalid Docker metadata for {service}") from exc


def _preflight_qwen(*, attempts: int, interval_seconds: float) -> dict[str, Any]:
    api_key, expected_identity = load_qwen_expected_settings()
    return run_qwen_preflight(
        base_url="http://127.0.0.1:8766",
        api_key=api_key,
        expected_identity=expected_identity,
        attempts=attempts,
        interval_seconds=interval_seconds,
    )


def _run_live_soak(evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    source_root = str((ROOT / "src").resolve())
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        source_root
        if not existing_pythonpath
        else os.pathsep.join((source_root, existing_pythonpath))
    )
    completed = _run(
        [
            sys.executable,
            "scripts/soak_golden_path.py",
            "--url",
            "http://localhost",
            "--duration",
            "0",
            "--turns",
            "30",
            "--turn-timeout",
            "60",
            "--probe-seconds",
            "5",
            "--audio-p50-ms",
            "3000",
            "--audio-p95-ms",
            "5000",
            "--media-p95-ms",
            "0",
            "--evidence-dir",
            str(evidence_dir),
        ],
        environment=environment,
    )
    output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not output_lines:
        raise ReleaseGateError("Thirty-turn soak did not report an evidence path")
    evidence_path = Path(output_lines[-1])
    if not evidence_path.is_absolute():
        evidence_path = ROOT / evidence_path
    if not evidence_path.exists():
        raise ReleaseGateError("Thirty-turn soak evidence file is missing")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise ReleaseGateError("Thirty-turn soak evidence must be a JSON object")
    validate_live_soak_evidence(evidence)
    return evidence


def _run_playwright(evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise ReleaseGateError("pnpm is required for fresh Playwright release evidence")
    environment = dict(os.environ)
    environment["PLAYWRIGHT_EVIDENCE_DIR"] = str(evidence_dir.resolve())
    _run(
        [pnpm, "exec", "node", "streaming-tts-smoke.mjs"],
        cwd=ROOT / "frontend",
        environment=environment,
    )
    evidence_path = evidence_dir / "evidence.json"
    if not evidence_path.exists():
        raise ReleaseGateError("Playwright did not write fresh structured evidence")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise ReleaseGateError("Fresh Playwright evidence must be a JSON object")
    validate_playwright_evidence(evidence)
    return evidence


def _ready(payload: Mapping[str, Any]) -> bool:
    return payload.get("ready") is True or payload.get("status") in {"ok", "ready"}


def run_release_gate(
    *,
    plan: Path,
    compose_file: Path,
    qwen_compose_file: Path,
    evidence_root: Path,
    attempts: int,
    interval_seconds: float,
) -> dict[str, Any]:
    """Run the persistent-Qwen, Animetta-only rebuild, and fresh acceptance protocol."""
    environment_fields = validate_release_environment(os.environ)
    if not plan.exists():
        raise ReleaseGateError(f"Frozen quality plan does not exist: {plan}")
    started_at = datetime.now(UTC)
    evidence_root.mkdir(parents=True, exist_ok=True)

    qwen_before = _container_metadata(qwen_compose_file, "qwen-tts")
    _run([sys.executable, "scripts/runtime_lifecycle.py", "qwen-up"])
    qwen_ready = _preflight_qwen(attempts=attempts, interval_seconds=interval_seconds)
    qwen_after_preflight = _container_metadata(qwen_compose_file, "qwen-tts")
    if qwen_after_preflight != qwen_before:
        raise ReleaseGateError("Routine Qwen preflight mutated the persistent rollback container")

    _run([sys.executable, "scripts/runtime_lifecycle.py", "anima-down"])
    _run([sys.executable, "scripts/runtime_lifecycle.py", "anima-up"])
    health = _wait_json(
        "http://localhost/health",
        lambda payload: payload.get("status") == "ok",
        attempts=attempts,
        interval_seconds=interval_seconds,
        description="Animetta health",
    )
    readiness = _wait_json(
        "http://localhost/ready",
        _ready,
        attempts=attempts,
        interval_seconds=interval_seconds,
        description="production readiness",
    )
    validate_production_readiness(readiness)
    frontend_before = _frontend_probe("http://localhost/")

    live_soak = _run_live_soak(evidence_root / "thirty-turn-soak")
    playwright = _run_playwright(evidence_root / "playwright")
    frontend_after = _frontend_probe("http://localhost/")

    animetta_logs = _run(
        _compose(compose_file, "logs", "--no-color", "--since", started_at.isoformat())
    ).stdout
    qwen_logs = _run(
        _compose(qwen_compose_file, "logs", "--no-color", "--since", started_at.isoformat())
    ).stdout
    (evidence_root / "animetta-docker.log").write_text(animetta_logs, encoding="utf-8")
    (evidence_root / "qwen-docker.log").write_text(qwen_logs, encoding="utf-8")
    assert_clean_logs(animetta_logs)
    assert_clean_logs(qwen_logs)

    qwen_after = _container_metadata(qwen_compose_file, "qwen-tts")
    if qwen_after != qwen_before:
        raise ReleaseGateError("Animetta release protocol mutated the persistent Qwen container")

    return {
        "schema_version": 2,
        "status": "passed",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "plan": str(plan),
        "main_compose_file": str(compose_file),
        "qwen_compose_file": str(qwen_compose_file),
        "environment_fields": environment_fields,
        "qwen_ready": qwen_ready,
        "persistent_qwen": {
            "preserved": True,
            "before": qwen_before,
            "after_preflight": qwen_after_preflight,
            "after": qwen_after,
            "build_actions": 0,
            "recreate_actions": 0,
        },
        "health": health,
        "readiness": readiness,
        "frontend_before": frontend_before,
        "live_soak": live_soak,
        "playwright": playwright,
        "frontend_after": frontend_after,
        "clean_logs": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, default=ROOT / "docker-compose.yml")
    parser.add_argument(
        "--qwen-compose-file",
        type=Path,
        default=ROOT / "docker-compose.qwen.yml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "test-impact" / "release-runtime" / "evidence.json",
    )
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env", override=False)
    try:
        evidence = run_release_gate(
            plan=args.plan.resolve(),
            compose_file=args.compose_file.resolve(),
            qwen_compose_file=args.qwen_compose_file.resolve(),
            evidence_root=args.output.parent.resolve(),
            attempts=args.attempts,
            interval_seconds=args.interval_seconds,
        )
    except (OSError, ValueError, ReleaseGateError) as exc:
        evidence = {
            "schema_version": 2,
            "status": "failed",
            "finished_at": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2), file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
