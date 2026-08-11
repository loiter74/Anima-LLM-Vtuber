"""Cross-platform lifecycle operations for host-local Qwen TTS and Animetta."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from animetta.host_tts_contract import HOST_TTS_CONTRACT  # noqa: E402

HOST_TTS_RUNTIME_ROOT = Path(r"D:\AnimaModelAuditions\qwen3-tts-1.7b-streaming-20260726")
HOST_TTS_PYTHON = HOST_TTS_RUNTIME_ROOT / "venv" / "Scripts" / "python.exe"
HOST_TTS_PID_FILE = HOST_TTS_RUNTIME_ROOT / "host-tts.pid.json"
HOST_TTS_LOG_FILE = HOST_TTS_RUNTIME_ROOT / "log" / "host-tts.log"
HOST_TTS_BASE_URL = "http://127.0.0.1:8767"
HOST_TTS_IDENTITY = HOST_TTS_CONTRACT.identity()

OPERATIONS = (
    "host-tts-up",
    "host-tts-status",
    "host-tts-stop",
    "anima-up",
    "anima-selftest-up",
    "anima-down",
)


def _run(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> None:
    process_environment = os.environ.copy()
    if environment:
        process_environment.update(environment)
    subprocess.run(command, cwd=ROOT, check=True, env=process_environment)


def _read_host_pid() -> int | None:
    try:
        payload = json.loads(HOST_TTS_PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    pid = payload.get("pid") if isinstance(payload, dict) else None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None


def _host_process_command_line(pid: int) -> str | None:
    if sys.platform != "win32":
        return None
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' "
            "-ErrorAction SilentlyContinue).CommandLine"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    command_line = result.stdout.strip()
    return command_line or None


def _is_expected_host_process(pid: int) -> bool:
    command_line = _host_process_command_line(pid)
    if command_line is None:
        return False
    normalized = command_line.casefold()
    return "animetta_qwen_tts" in normalized and str(HOST_TTS_PYTHON).casefold() in normalized


def _host_token() -> str:
    load_dotenv(ROOT / ".env", override=False)
    return os.getenv("QWEN_TTS_API_KEY", "").strip()


def _host_request_json(path: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"{HOST_TTS_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Host TTS returned a non-object response")
    return payload


def _host_tts_status() -> dict[str, object]:
    pid = _read_host_pid()
    if pid is None or not _is_expected_host_process(pid):
        return {"running": False, "ready": False}

    token = _host_token()
    if not token:
        return {"running": True, "ready": False, "error_category": "configuration"}
    try:
        ready = _host_request_json("/ready", token)
        identity = _host_request_json("/v1/identity", token)
    except (
        OSError,
        TimeoutError,
        ValueError,
        urllib.error.URLError,
    ):
        return {"running": True, "ready": False, "error_category": "connection"}

    identity_matches = all(
        identity.get(field) == expected for field, expected in HOST_TTS_IDENTITY.items()
    )
    is_ready = ready.get("ready") is True and identity_matches
    status: dict[str, object] = {
        "running": True,
        "ready": is_ready,
        "identity_matches": identity_matches,
    }
    if not identity_matches:
        status["error_category"] = "identity"
    return status


def _remove_host_pid_file() -> None:
    with contextlib.suppress(OSError):
        HOST_TTS_PID_FILE.unlink(missing_ok=True)


def _terminate_host_process(pid: int) -> None:
    if not _is_expected_host_process(pid):
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        check=False,
        capture_output=True,
        timeout=15,
    )


def _start_host_tts_process(token: str) -> int:
    if not HOST_TTS_PYTHON.is_file():
        raise RuntimeError("Host TTS Python runtime is unavailable")
    if not HOST_TTS_RUNTIME_ROOT.is_dir():
        raise RuntimeError("Host TTS runtime directory is unavailable")

    HOST_TTS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    python_paths = [str(ROOT / "src"), str(HOST_TTS_RUNTIME_ROOT)]
    if existing_pythonpath:
        python_paths.append(existing_pythonpath)
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(python_paths),
            "QWEN_TTS_ENGINE": "gguf-host",
            "QWEN_TTS_BIND_HOST": "127.0.0.1",
            "QWEN_TTS_BIND_PORT": "8767",
            "QWEN_TTS_API_KEY": token,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )

    creationflags = 0
    startupinfo = None
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    with HOST_TTS_LOG_FILE.open("ab") as log_file:
        process = subprocess.Popen(
            [str(HOST_TTS_PYTHON), "-m", "animetta_qwen_tts"],
            cwd=HOST_TTS_RUNTIME_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
    HOST_TTS_PID_FILE.write_text(
        json.dumps({"pid": process.pid}, separators=(",", ":")),
        encoding="utf-8",
    )
    return process.pid


def _host_tts_up(*, best_effort: bool) -> bool:
    try:
        status = _host_tts_status()
        if status.get("ready") is True:
            return True

        existing_pid = _read_host_pid()
        if existing_pid is not None and _is_expected_host_process(existing_pid):
            _terminate_host_process(existing_pid)
        _remove_host_pid_file()

        token = _host_token()
        if not token:
            raise RuntimeError("QWEN_TTS_API_KEY is not configured")
        pid = _start_host_tts_process(token)

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = _host_tts_status()
            if status.get("ready") is True:
                return True
            if not _is_expected_host_process(pid):
                break
            time.sleep(2)
        raise RuntimeError("Host TTS did not become ready")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        if best_effort:
            print(
                "[WARN] Host TTS unavailable; Animetta will continue with cloud TTS",
                file=sys.stderr,
            )
            return False
        raise


def _host_tts_stop() -> None:
    pid = _read_host_pid()
    if pid is not None:
        _terminate_host_process(pid)
    _remove_host_pid_file()


def _preflight(*, wait: bool) -> list[str]:
    command = [sys.executable, "scripts/qwen_preflight.py"]
    if wait:
        command.append("--wait")
    return command


def run_operation(operation: str) -> None:
    """Execute one explicit lifecycle operation."""
    if operation == "host-tts-up":
        _host_tts_up(best_effort=False)
    elif operation == "host-tts-status":
        print(json.dumps(_host_tts_status(), sort_keys=True))
    elif operation == "host-tts-stop":
        _host_tts_stop()
    elif operation == "anima-up":
        _host_tts_up(best_effort=False)
        _run(_preflight(wait=False))
        runtime_environment = {"ANIMETTA_PROFILE": os.getenv("ANIMETTA_PROFILE") or "production"}
        _run(
            ["docker", "compose", "build", "animetta"],
            environment=runtime_environment,
        )
        _run(
            ["docker", "compose", "up", "-d", "--no-build", "animetta"],
            environment=runtime_environment,
        )
    elif operation == "anima-selftest-up":
        _host_tts_up(best_effort=False)
        _run(_preflight(wait=True))
        selftest_environment = {"ANIMETTA_PROFILE": "selftest"}
        _run(
            ["docker", "compose", "build", "animetta"],
            environment=selftest_environment,
        )
        _run(
            ["docker", "compose", "up", "-d", "--no-build", "animetta"],
            environment=selftest_environment,
        )
    elif operation == "anima-down":
        _run(["docker", "compose", "down", "--remove-orphans"])
    else:
        raise ValueError(f"Unknown lifecycle operation: {operation}")


class _SystemLifecycleDriver:
    def __init__(self, *, evidence_root: Path) -> None:
        from tooling.execution_feedback.lifecycle import LifecycleDriverObservation

        self._observation_type = LifecycleDriverObservation
        self._evidence_root = evidence_root.resolve()
        self._evidence_root.mkdir(parents=True, exist_ok=True)

    def _evidence(self, name: str, contents: str) -> str:
        path = self._evidence_root / f"{name}.log"
        path.write_text(contents, encoding="utf-8")
        return path.resolve().as_posix()

    def run_command(self, command: tuple[str, ...], *, timeout_seconds: float):
        if command == ("host-tts-start",):
            ready = _host_tts_up(best_effort=False)
            return self._observation_type(
                succeeded=ready,
                summary="Host TTS is ready",
                evidence_refs=(self._evidence("host-tts-readiness", f"ready={ready}\n"),),
                exit_code=0,
            )
        if command == ("host-tts-status",):
            status = _host_tts_status()
            payload = json.dumps(status, sort_keys=True)
            return self._observation_type(
                succeeded=True,
                summary=payload,
                evidence_refs=(self._evidence("host-tts-status", f"{payload}\n"),),
                exit_code=0,
            )
        if command == ("host-tts-stop",):
            _host_tts_stop()
            status = _host_tts_status()
            stopped = status.get("running") is False
            payload = json.dumps(status, sort_keys=True)
            return self._observation_type(
                succeeded=stopped,
                summary="Host TTS stopped" if stopped else "Host TTS is still running",
                evidence_refs=(self._evidence("host-tts-stop", f"{payload}\n"),),
                exit_code=0 if stopped else 1,
            )
        if command == ("host-tts-preflight",):
            command = tuple(_preflight(wait=False))
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
            )
            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            reference = self._evidence(
                f"command-{hashlib.sha256(repr(command).encode()).hexdigest()[:12]}",
                output,
            )
            return self._observation_type(
                succeeded=completed.returncode == 0,
                summary=(f"command completed with exit code {completed.returncode}"),
                evidence_refs=(reference,),
                exit_code=completed.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            output = "\n".join(str(part) for part in (exc.stdout, exc.stderr) if part is not None)
            reference = self._evidence("command-timeout", output)
            return self._observation_type(
                succeeded=False,
                summary=f"command exceeded {timeout_seconds:g} seconds",
                evidence_refs=(reference,),
            )

    def check_http(self, target: str, *, timeout_seconds: float):
        deadline = time.monotonic() + timeout_seconds
        last_error = "no response"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(target, timeout=3) as response:  # noqa: S310
                    body = response.read().decode("utf-8", errors="replace")
                    healthy = response.status == 200 and (
                        not target.endswith("/health") or '"status":"ok"' in body.replace(" ", "")
                    )
                    if healthy:
                        reference = self._evidence(
                            f"http-{hashlib.sha256(target.encode()).hexdigest()[:12]}",
                            body,
                        )
                        return self._observation_type(
                            succeeded=True,
                            summary=f"HTTP 200 from {target}",
                            evidence_refs=(reference,),
                            exit_code=0,
                        )
                    last_error = f"HTTP {response.status} or invalid health body"
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(5)
        reference = self._evidence("http-timeout", last_error)
        return self._observation_type(
            succeeded=False,
            summary=f"HTTP readiness timed out for {target}: {last_error}",
            evidence_refs=(reference,),
        )

    def check_logs(self, command: tuple[str, ...], *, timeout_seconds: float):
        observation = self.run_command(command, timeout_seconds=timeout_seconds)
        output = "\n".join(
            Path(reference).read_text(encoding="utf-8", errors="replace")
            for reference in observation.evidence_refs
            if Path(reference).is_file()
        )
        has_error = re.search(r"(?im)(traceback|\berror\b)", output) is not None
        return self._observation_type(
            succeeded=observation.succeeded and not has_error,
            summary="logs contain no Traceback or ERROR"
            if not has_error
            else "logs contain errors",
            evidence_refs=observation.evidence_refs,
            exit_code=observation.exit_code,
        )


def _bounded_input_fingerprint(operation: str) -> str:
    material = b"\0".join(
        (
            operation.encode(),
            Path(__file__).read_bytes(),
            (ROOT / "tooling" / "execution_feedback" / "lifecycle.py").read_bytes(),
        )
    )
    return hashlib.sha256(material).hexdigest()


def _build_lease_id(run_id: str) -> str:
    """Scope the BuildKit lease to one resumable lifecycle run."""

    return f"{run_id}-animetta-build"


async def run_bounded_operation(
    operation: str,
    *,
    run_id: str,
    artifacts_root: Path,
) -> int:
    from tooling.execution_feedback import (
        ActionResult,
        FeedbackContext,
        FeedbackStatus,
        IterationPlanStore,
        LeaseManager,
        PlanStepCheckpoint,
        supervise_feedback_window,
    )
    from tooling.execution_feedback.lifecycle import (
        BuildStepController,
        LeasedSubprocessBuildDriver,
        LifecycleStepContract,
        LifecycleStepExecutor,
        freeze_lifecycle_plan,
    )

    frozen = freeze_lifecycle_plan(
        operation,
        input_fingerprint=_bounded_input_fingerprint(operation),
        run_id=run_id,
    )
    store = IterationPlanStore(artifacts_root)
    store.write_plan(frozen.plan)
    run_root = artifacts_root.resolve() / run_id
    build_log = f"{run_id}/animetta-build.log"
    build_driver = LeasedSubprocessBuildDriver(
        workspace_root=ROOT,
        artifacts_root=artifacts_root.resolve(),
        receipt_path=run_root / "animetta-build-receipt.json",
    )
    build_controller = BuildStepController(
        lease_manager=LeaseManager(store),
        driver=build_driver,
        run_id=run_id,
        owner="lifecycle-worker",
        lease_id=_build_lease_id(run_id),
        command=("docker", "compose", "build", "animetta"),
        command_digest=hashlib.sha256(b"docker compose build animetta").hexdigest(),
        log_path=build_log,
    )
    executor = LifecycleStepExecutor(
        driver=_SystemLifecycleDriver(evidence_root=run_root / "evidence"),
        build_controller=build_controller,
    )

    for step_contract, step_spec in zip(frozen.steps, frozen.plan.steps, strict=True):
        recovered = store.recover_latest_result(run_id, step_contract.id)
        if recovered.result is not None and recovered.result.status is FeedbackStatus.PASSED:
            continue
        sequence = (recovered.latest_window_sequence or 0) + 1

        async def action(
            _context: FeedbackContext,
            *,
            contract: LifecycleStepContract = step_contract,
        ) -> ActionResult:
            return await asyncio.to_thread(executor.run, contract, now=datetime.now(UTC))

        result = await supervise_feedback_window(
            run_id=run_id,
            step=step_spec,
            window_sequence=sequence,
            store=store,
            action=action,
            emit=lambda payload: print(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        if result.status is FeedbackStatus.PASSED:
            result_reference = (
                (
                    run_root
                    / "steps"
                    / step_contract.id
                    / "windows"
                    / f"{sequence:06d}"
                    / "result.json"
                )
                .resolve()
                .as_posix()
            )
            evidence = result.evidence_refs or (result_reference,)
            reuse_fingerprint = hashlib.sha256(
                f"{frozen.plan.input_fingerprint}:{step_contract.id}".encode()
            ).hexdigest()
            store.write_checkpoint(
                PlanStepCheckpoint(
                    run_id=run_id,
                    step_id=step_contract.id,
                    status=FeedbackStatus.PASSED,
                    reuse_fingerprint=reuse_fingerprint,
                    evidence_refs=evidence,
                    result_reference=result_reference,
                    committed_at=result.feedback_at,
                )
            )
            continue
        return 2 if result.status is FeedbackStatus.IN_PROGRESS else 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=ROOT / "artifacts" / "iteration-plans",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_id = args.run_id or f"{args.operation}-{uuid.uuid4().hex[:12]}"
    print(json.dumps({"run_id": run_id, "mode": "bounded-feedback"}, sort_keys=True))
    return asyncio.run(
        run_bounded_operation(
            args.operation,
            run_id=run_id,
            artifacts_root=args.artifacts_root,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
