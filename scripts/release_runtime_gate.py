#!/usr/bin/env python3
"""Cold production Docker release gate with fresh runtime and browser evidence."""

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
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENVIRONMENT = (
    "ALICE_REF_AUDIO",
    "DEEPSEEK_API_KEY",
    "HF_CACHE_DIR",
    "MIMO_API_KEY",
    "QWEN_TTS_API_KEY",
)
_FORBIDDEN_LOG_PATTERN = re.compile(
    r"Traceback|(?:^|[|\s])(?:ERROR|CRITICAL|FATAL)(?:[|\s:]|$)",
    re.MULTILINE,
)


class ReleaseGateError(RuntimeError):
    """Release evidence is incomplete or unsafe."""


def validate_release_environment(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Validate release-only secrets and mounts without returning their values."""
    missing = [name for name in REQUIRED_ENVIRONMENT if not environment.get(name, "").strip()]
    if missing:
        raise ReleaseGateError("Missing release environment fields: " + ", ".join(sorted(missing)))
    for name in ("HF_CACHE_DIR", "ALICE_REF_AUDIO"):
        if not Path(environment[name]).exists():
            raise ReleaseGateError(f"Release mount path does not exist: {name}")
    return tuple(sorted(REQUIRED_ENVIRONMENT))


def validate_smoke_evidence(evidence: Mapping[str, Any]) -> None:
    """Require real Alice WAV evidence from the isolated remote Qwen service."""
    provider = evidence.get("provider")
    resolved = provider.get("resolved") if isinstance(provider, Mapping) else None
    expected_identity = (
        isinstance(provider, Mapping)
        and provider.get("type") == "remote"
        and provider.get("provider") == "qwen3"
        and provider.get("model") == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
        and provider.get("voice") == "alice"
        and isinstance(resolved, Mapping)
        and resolved.get("provider") == provider.get("provider")
        and resolved.get("model") == provider.get("model")
        and resolved.get("voice") == provider.get("voice")
        and resolved.get("revision") == "5d83992436eae1d760afd27aff78a71d676296fc"
    )
    if not expected_identity:
        raise ReleaseGateError("Alice smoke provider identity is not exact and resolved")
    if (
        evidence.get("ok") is not True
        or int(evidence.get("audio_bytes", 0)) <= 44
        or int(evidence.get("volume_samples", 0)) < 1
        or int(evidence.get("volume_nonzero", 0)) < 1
    ):
        raise ReleaseGateError("Alice smoke did not produce valid WAV evidence")


def validate_production_readiness(payload: Mapping[str, Any]) -> None:
    """Require the exact production Qwen/Alice identity in application readiness."""
    components = payload.get("components")
    tts = components.get("tts") if isinstance(components, Mapping) else None
    configured = tts.get("configured") if isinstance(tts, Mapping) else None
    resolved = tts.get("resolved") if isinstance(tts, Mapping) else None
    expected = {
        "provider": "qwen3",
        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "voice": "alice",
    }
    if not (
        _ready(payload)
        and payload.get("profile") == "production"
        and isinstance(tts, Mapping)
        and tts.get("ready") is True
        and isinstance(configured, Mapping)
        and configured.get("type") == "remote"
        and all(configured.get(key) == value for key, value in expected.items())
        and isinstance(resolved, Mapping)
        and all(resolved.get(key) == value for key, value in expected.items())
    ):
        raise ReleaseGateError("Application readiness lacks exact production Qwen/Alice identity")


def validate_turn_probe_evidence(
    evidence: Mapping[str, Any],
    *,
    expect: str,
    conversation_id: str,
) -> None:
    """Require application-level typed degradation or recovered audio continuity."""
    degraded = evidence.get("degraded") is True
    if not (
        evidence.get("status") == "passed"
        and evidence.get("conversation_id") == conversation_id
        and bool(str(evidence.get("safe_output", "")).strip())
        and int(evidence.get("expression_count", 0)) >= 1
        and int(evidence.get("action_count", 0)) >= 1
    ):
        raise ReleaseGateError("Application turn probe lacks text/Live2D continuity")
    if expect == "degraded" and not (
        degraded
        and int(evidence.get("degradation_count", 0)) == 1
        and int(evidence.get("audio_count", 0)) == 0
    ):
        raise ReleaseGateError("Qwen outage did not produce one typed media degradation")
    if expect == "audio" and not (
        not degraded
        and int(evidence.get("degradation_count", 0)) == 0
        and int(evidence.get("audio_count", 0)) == 1
    ):
        raise ReleaseGateError("Next turn did not retry the configured provider with audio")


def validate_playwright_evidence(evidence: Mapping[str, Any]) -> None:
    """Reject empty-shell pages and incomplete production browser acceptance."""
    core = evidence.get("core_ui")
    release = evidence.get("release_acceptance")
    audio = release.get("audio") if isinstance(release, Mapping) else None
    if not (
        evidence.get("status") == "passed"
        and isinstance(core, Mapping)
        and core.get("passed") is True
        and isinstance(release, Mapping)
        and release.get("passed") is True
        and release.get("provider_rows_exact") is True
        and release.get("chinese_turn_complete") is True
        and isinstance(audio, Mapping)
        and audio.get("play_calls") == 1
        and audio.get("play_resolved") == 1
        and audio.get("ended") == 1
        and audio.get("play_rejected") == 0
    ):
        raise ReleaseGateError("Fresh Playwright production evidence is incomplete")


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


def _run_alice_smoke(compose_file: Path) -> dict[str, Any]:
    completed = _run(
        _compose(
            compose_file,
            "exec",
            "-T",
            "animetta",
            "python",
            "scripts/smoke_qwen_alice.py",
        )
    )
    try:
        evidence = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseGateError("Alice smoke did not emit JSON evidence") from exc
    if not isinstance(evidence, dict):
        raise ReleaseGateError("Alice smoke evidence must be a JSON object")
    validate_smoke_evidence(evidence)
    return evidence


def _run_turn_probe(
    compose_file: Path,
    *,
    expect: str,
    conversation_id: str,
    text: str,
) -> dict[str, Any]:
    completed = _run(
        _compose(
            compose_file,
            "exec",
            "-T",
            "animetta",
            "python",
            "scripts/probe_release_turn.py",
            "--expect",
            expect,
            "--conversation-id",
            conversation_id,
            "--text",
            text,
        )
    )
    try:
        evidence = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseGateError("Application turn probe did not emit JSON evidence") from exc
    if not isinstance(evidence, dict):
        raise ReleaseGateError("Application turn probe evidence must be a JSON object")
    validate_turn_probe_evidence(
        evidence,
        expect=expect,
        conversation_id=conversation_id,
    )
    return evidence


def _container_id(compose_file: Path, service: str) -> str:
    container_id = _run(_compose(compose_file, "ps", "-q", service)).stdout.strip()
    if not container_id:
        raise ReleaseGateError(f"No running container found for {service}")
    return container_id


def _run_playwright(evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise ReleaseGateError("pnpm is required for fresh Playwright release evidence")
    environment = dict(os.environ)
    environment["PLAYWRIGHT_EVIDENCE_DIR"] = str(evidence_dir.resolve())
    environment["PLAYWRIGHT_RELEASE_MODE"] = "1"
    _run(
        [pnpm, "exec", "node", "smoke-test.mjs"],
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
    evidence_root: Path,
    attempts: int,
    interval_seconds: float,
) -> dict[str, Any]:
    """Execute the mandatory cold release topology protocol."""
    environment_fields = validate_release_environment(os.environ)
    started_at = datetime.now(UTC)
    evidence_root.mkdir(parents=True, exist_ok=True)

    _run(_compose(compose_file, "down", "--remove-orphans"))
    build = _run(
        [
            sys.executable,
            "-m",
            "tooling.quality",
            "docker-build",
            "--plan",
            str(plan),
            "--compose-file",
            str(compose_file),
            "--no-cache",
            "--json",
        ]
    )
    build_evidence = json.loads(build.stdout)
    if build_evidence.get("status") != "passed" or len(build_evidence.get("actions", ())) != 2:
        raise ReleaseGateError("Release gate must cold-build both Docker image scopes")

    _run(_compose(compose_file, "up", "-d", "--no-build"))
    health = _wait_json(
        "http://localhost/health",
        lambda payload: payload.get("status") == "ok",
        attempts=attempts,
        interval_seconds=interval_seconds,
        description="Animetta health",
    )
    initial_ready = _wait_json(
        "http://localhost/ready",
        _ready,
        attempts=attempts,
        interval_seconds=interval_seconds,
        description="production readiness",
    )
    validate_production_readiness(initial_ready)
    frontend_before = _frontend_probe("http://localhost/")
    initial_smoke = _run_alice_smoke(compose_file)

    conversation_id = str(uuid4())
    animetta_container_before = _container_id(compose_file, "animetta")
    qwen_container_before = _container_id(compose_file, "qwen-tts")
    _run(_compose(compose_file, "stop", "qwen-tts"))
    outage = _wait_json(
        "http://localhost/ready",
        lambda payload: not _ready(payload),
        attempts=max(24, attempts // 4),
        interval_seconds=interval_seconds,
        description="remote TTS outage",
    )
    outage_turn = _run_turn_probe(
        compose_file,
        expect="degraded",
        conversation_id=conversation_id,
        text="这一轮用于验证音频降级，但必须保留文字和 Live2D。",
    )
    _run(_compose(compose_file, "start", "qwen-tts"))
    recovered_ready = _wait_json(
        "http://localhost/ready",
        _ready,
        attempts=attempts,
        interval_seconds=interval_seconds,
        description="same-container remote TTS recovery",
    )
    validate_production_readiness(recovered_ready)
    animetta_container_after = _container_id(compose_file, "animetta")
    qwen_container_after = _container_id(compose_file, "qwen-tts")
    if animetta_container_before != animetta_container_after:
        raise ReleaseGateError("Qwen recovery did not preserve the Animetta container")
    if qwen_container_before != qwen_container_after:
        raise ReleaseGateError("Qwen recovery recreated its container instead of restarting it")
    recovery_turn = _run_turn_probe(
        compose_file,
        expect="audio",
        conversation_id=conversation_id,
        text="故障已经撤销，请继续使用同一个 Alice 声音确认恢复。",
    )
    recovery_smoke = _run_alice_smoke(compose_file)
    frontend_after = _frontend_probe("http://localhost/")
    playwright = _run_playwright(evidence_root / "playwright")

    logs = _run(
        _compose(compose_file, "logs", "--no-color", "--since", started_at.isoformat())
    ).stdout
    (evidence_root / "docker.log").write_text(logs, encoding="utf-8")
    assert_clean_logs(logs)

    return {
        "schema_version": 1,
        "status": "passed",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "plan": str(plan),
        "environment_fields": environment_fields,
        "build": build_evidence,
        "health": health,
        "initial_ready": initial_ready,
        "frontend_before": frontend_before,
        "initial_alice_smoke": initial_smoke,
        "conversation_id": conversation_id,
        "animetta_container_before": animetta_container_before,
        "animetta_container_after": animetta_container_after,
        "outage": outage,
        "outage_turn": outage_turn,
        "recovered_ready": recovered_ready,
        "qwen_container_before": qwen_container_before,
        "qwen_container_after": qwen_container_after,
        "same_container_recovery": True,
        "recovery_turn": recovery_turn,
        "recovery_alice_smoke": recovery_smoke,
        "frontend_after": frontend_after,
        "playwright": playwright,
        "clean_logs": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, default=ROOT / "docker-compose.yml")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "test-impact" / "release-runtime" / "evidence.json",
    )
    parser.add_argument("--attempts", type=int, default=120)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env", override=False)
    try:
        evidence = run_release_gate(
            plan=args.plan.resolve(),
            compose_file=args.compose_file.resolve(),
            evidence_root=args.output.parent.resolve(),
            attempts=args.attempts,
            interval_seconds=args.interval_seconds,
        )
    except (OSError, ValueError, ReleaseGateError) as exc:
        evidence = {
            "schema_version": 1,
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
