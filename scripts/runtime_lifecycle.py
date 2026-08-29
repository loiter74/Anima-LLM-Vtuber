"""Cross-platform lifecycle operations for host-local AI services and Animetta."""

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

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from animetta.host_rvc_contract import HOST_RVC_CONTRACT  # noqa: E402
from animetta.host_tts_contract import HOST_TTS_CONTRACT  # noqa: E402

HOST_TTS_RUNTIME_ROOT = Path(r"D:\AnimaModelAuditions\qwen3-tts-1.7b-streaming-20260726")
HOST_TTS_PYTHON = HOST_TTS_RUNTIME_ROOT / "venv" / "Scripts" / "python.exe"
HOST_TTS_PID_FILE = HOST_TTS_RUNTIME_ROOT / "host-tts.pid.json"
HOST_TTS_LOG_FILE = HOST_TTS_RUNTIME_ROOT / "log" / "host-tts.log"
HOST_TTS_BASE_URL = "http://127.0.0.1:8767"
HOST_TTS_IDENTITY = HOST_TTS_CONTRACT.identity()
HOST_RVC_RUNTIME_ROOT = HOST_RVC_CONTRACT.runtime_root
HOST_RVC_PYTHON = HOST_RVC_CONTRACT.python_executable
HOST_RVC_PID_FILE = HOST_RVC_RUNTIME_ROOT / "host-rvc.pid.json"
HOST_RVC_LOG_FILE = HOST_RVC_RUNTIME_ROOT / "log" / "host-rvc.log"
HOST_RVC_BASE_URL = "http://127.0.0.1:8769"
HOST_RVC_IDENTITY = HOST_RVC_CONTRACT.identity()
LOCAL_ANIMETTA_IMAGE = "animetta:local"
GHCR_ANIMETTA_IMAGE = "ghcr.io/loiter74/animetta"
_ANIMETTA_BUILD_COMMAND = ("docker", "compose", "build", "animetta")
_DEPLOY_IMAGE_PATTERN = re.compile(
    rf"^(?:{re.escape(GHCR_ANIMETTA_IMAGE)}:"
    r"(?:main|sha-[0-9a-f]{40})|"
    rf"{re.escape(GHCR_ANIMETTA_IMAGE)}@sha256:[0-9a-f]{{64}})$"
)

OPERATIONS = (
    "host-tts-up",
    "host-tts-status",
    "host-tts-stop",
    "host-rvc-up",
    "host-rvc-status",
    "host-rvc-stop",
    "anima-up",
    "anima-deploy",
    "anima-selftest-up",
    "anima-down",
)


def _validate_deploy_image(value: str) -> str:
    image = value.strip()
    if _DEPLOY_IMAGE_PATTERN.fullmatch(image) is None:
        raise ValueError(
            "image must be ghcr.io/loiter74/animetta:main, "
            "ghcr.io/loiter74/animetta:sha-<40 lowercase hex characters>, "
            "or ghcr.io/loiter74/animetta@sha256:<64 lowercase hex characters>"
        )
    return image


def _image_argument(value: str) -> str:
    try:
        return _validate_deploy_image(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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


def _host_tts_listener_pid() -> int | None:
    if sys.platform != "win32":
        return None
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            "Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8767 "
            "-State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty OwningProcess"
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
        pid = int(result.stdout.strip())
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    return pid if pid > 0 else None


def _environment_secret(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        value = dotenv_values(ROOT / ".env").get(name)
    return value.strip() if isinstance(value, str) else ""


def _host_token() -> str:
    return _environment_secret("QWEN_TTS_API_KEY")


def _animetta_access_token() -> str:
    return _environment_secret("ANIMETTA_ACCESS_TOKEN")


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
        pid = _host_tts_listener_pid()
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
    for _ in range(50):
        if not _is_expected_host_process(pid):
            return
        time.sleep(0.1)
    raise RuntimeError("Host TTS process tree did not stop")


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
    pids = {_read_host_pid(), _host_tts_listener_pid()}
    for pid in pids:
        if pid is not None:
            _terminate_host_process(pid)
    _remove_host_pid_file()


def _read_host_rvc_pid() -> int | None:
    try:
        payload = json.loads(HOST_RVC_PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    pid = payload.get("pid") if isinstance(payload, dict) else None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None


def _is_expected_host_rvc_process(pid: int) -> bool:
    command_line = _host_process_command_line(pid)
    if command_line is None:
        return False
    normalized = command_line.casefold()
    return "animetta_rvc_host" in normalized and str(HOST_RVC_PYTHON).casefold() in normalized


def _host_rvc_request_json(path: str, token: str = "") -> dict[str, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{HOST_RVC_BASE_URL}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Host RVC returned a non-object response")
    return payload


def _host_rvc_status() -> dict[str, object]:
    pid = _read_host_rvc_pid()
    if pid is None or not _is_expected_host_rvc_process(pid):
        return {"running": False, "ready": False}
    token = _host_token()
    if not token:
        return {"running": True, "ready": False, "error_category": "configuration"}
    try:
        ready = _host_rvc_request_json("/ready", token)
    except (OSError, TimeoutError, ValueError, urllib.error.URLError):
        return {"running": True, "ready": False, "error_category": "connection"}
    identity_matches = all(
        ready.get(field) == expected for field, expected in HOST_RVC_IDENTITY.items()
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


def _remove_host_rvc_pid_file() -> None:
    with contextlib.suppress(OSError):
        HOST_RVC_PID_FILE.unlink(missing_ok=True)


def _terminate_host_rvc_process(pid: int) -> None:
    if not _is_expected_host_rvc_process(pid):
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        check=False,
        capture_output=True,
        timeout=15,
    )


def _start_host_rvc_process(token: str) -> int:
    if not HOST_RVC_PYTHON.is_file():
        raise RuntimeError("Host RVC Python runtime is unavailable")
    if not HOST_RVC_RUNTIME_ROOT.is_dir():
        raise RuntimeError("Host RVC runtime directory is unavailable")
    HOST_RVC_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    python_paths = [str(ROOT / "src"), str(HOST_RVC_RUNTIME_ROOT)]
    if existing_pythonpath:
        python_paths.append(existing_pythonpath)
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(python_paths),
            "QWEN_TTS_API_KEY": token,
            "RVC_HOST_BIND_HOST": "127.0.0.1",
            "RVC_HOST_BIND_PORT": "8769",
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
    with HOST_RVC_LOG_FILE.open("ab") as log_file:
        process = subprocess.Popen(
            [str(HOST_RVC_PYTHON), "-m", "animetta_rvc_host"],
            cwd=HOST_RVC_RUNTIME_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
    HOST_RVC_PID_FILE.write_text(
        json.dumps({"pid": process.pid}, separators=(",", ":")),
        encoding="utf-8",
    )
    return process.pid


def _host_rvc_up() -> bool:
    status = _host_rvc_status()
    if status.get("ready") is True:
        return True
    existing_pid = _read_host_rvc_pid()
    if existing_pid is not None and _is_expected_host_rvc_process(existing_pid):
        _terminate_host_rvc_process(existing_pid)
    _remove_host_rvc_pid_file()
    token = _host_token()
    if not token:
        raise RuntimeError("QWEN_TTS_API_KEY is not configured")
    pid = _start_host_rvc_process(token)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        status = _host_rvc_status()
        if status.get("ready") is True:
            return True
        if not _is_expected_host_rvc_process(pid):
            break
        time.sleep(2)
    raise RuntimeError("Host RVC did not become ready")


def _host_rvc_stop() -> None:
    pid = _read_host_rvc_pid()
    if pid is not None:
        _terminate_host_rvc_process(pid)
    _remove_host_rvc_pid_file()


def _preflight(*, wait: bool) -> list[str]:
    command = [sys.executable, "scripts/qwen_preflight.py"]
    if wait:
        command.append("--wait")
    return command


def _rvc_preflight(*, wait: bool) -> list[str]:
    command = [sys.executable, "scripts/rvc_preflight.py"]
    if wait:
        command.append("--wait")
    return command


def _prepare_host_runtimes(*, wait: bool) -> None:
    _host_tts_up(best_effort=False)
    _run(_preflight(wait=wait))
    _host_rvc_up()
    _run(_rvc_preflight(wait=wait))


def _compose_environment(*, image: str, profile: str | None = None) -> dict[str, str]:
    return {
        "ANIMETTA_IMAGE": image,
        "ANIMETTA_PROFILE": profile or os.getenv("ANIMETTA_PROFILE") or "production",
    }


def run_operation(operation: str, *, image: str | None = None) -> None:
    """Execute one explicit lifecycle operation."""
    if operation != "anima-deploy" and image is not None:
        raise ValueError("--image is only valid with anima-deploy")
    if operation == "host-tts-up":
        _host_tts_up(best_effort=False)
    elif operation == "host-tts-status":
        print(json.dumps(_host_tts_status(), sort_keys=True))
    elif operation == "host-tts-stop":
        _host_tts_stop()
    elif operation == "host-rvc-up":
        _host_rvc_up()
    elif operation == "host-rvc-status":
        print(json.dumps(_host_rvc_status(), sort_keys=True))
    elif operation == "host-rvc-stop":
        _host_rvc_stop()
    elif operation == "anima-up":
        _prepare_host_runtimes(wait=False)
        runtime_environment = _compose_environment(image=LOCAL_ANIMETTA_IMAGE)
        _run(
            list(_ANIMETTA_BUILD_COMMAND),
            environment=runtime_environment,
        )
        _run(
            ["docker", "compose", "up", "-d", "--no-build", "animetta"],
            environment=runtime_environment,
        )
    elif operation == "anima-deploy":
        selected_image = _validate_deploy_image(image or "")
        _prepare_host_runtimes(wait=False)
        deploy_environment = _compose_environment(image=selected_image)
        _run(
            ["docker", "compose", "pull", "--include-deps", "animetta"],
            environment=deploy_environment,
        )
        _run(
            [
                "docker",
                "image",
                "inspect",
                selected_image,
                "--format",
                "{{json .RepoDigests}}",
            ],
            environment=deploy_environment,
        )
        _run(
            ["docker", "compose", "up", "-d", "--no-build", "animetta"],
            environment=deploy_environment,
        )
    elif operation == "anima-selftest-up":
        _prepare_host_runtimes(wait=True)
        selftest_environment = _compose_environment(
            image=LOCAL_ANIMETTA_IMAGE,
            profile="selftest",
        )
        _run(
            list(_ANIMETTA_BUILD_COMMAND),
            environment=selftest_environment,
        )
        _run(
            ["docker", "compose", "up", "-d", "--no-build", "animetta"],
            environment=selftest_environment,
        )
    elif operation == "anima-down":
        _run(
            ["docker", "compose", "down", "--remove-orphans"],
            environment=_compose_environment(image=LOCAL_ANIMETTA_IMAGE),
        )
    else:
        raise ValueError(f"Unknown lifecycle operation: {operation}")


def _valid_http_body(target: str, body: str) -> bool:
    if not target.endswith(("/health", "/ready")):
        return True
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if target.endswith("/health"):
        return payload.get("status") == "ok"
    return payload.get("ready") is True or payload.get("status") in {"ok", "ready"}


class _SystemLifecycleDriver:
    def __init__(
        self,
        *,
        evidence_root: Path,
        environment: dict[str, str] | None = None,
        access_token: str | None = None,
    ) -> None:
        from tooling.execution_feedback.lifecycle import LifecycleDriverObservation

        self._observation_type = LifecycleDriverObservation
        self._evidence_root = evidence_root.resolve()
        self._evidence_root.mkdir(parents=True, exist_ok=True)
        self._environment = dict(environment or {})
        self._access_token = access_token or ""

    def _redact(self, contents: str) -> str:
        if self._access_token:
            contents = contents.replace(self._access_token, "[REDACTED]")
        return contents

    def _evidence(self, name: str, contents: str) -> str:
        path = self._evidence_root / f"{name}.log"
        contents = self._redact(contents)
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
        if command == ("host-rvc-start",):
            ready = _host_rvc_up()
            return self._observation_type(
                succeeded=ready,
                summary="Host RVC is ready",
                evidence_refs=(self._evidence("host-rvc-readiness", f"ready={ready}\n"),),
                exit_code=0,
            )
        if command == ("host-rvc-status",):
            status = _host_rvc_status()
            payload = json.dumps(status, sort_keys=True)
            return self._observation_type(
                succeeded=True,
                summary=payload,
                evidence_refs=(self._evidence("host-rvc-status", f"{payload}\n"),),
                exit_code=0,
            )
        if command == ("host-rvc-stop",):
            _host_rvc_stop()
            status = _host_rvc_status()
            stopped = status.get("running") is False
            payload = json.dumps(status, sort_keys=True)
            return self._observation_type(
                succeeded=stopped,
                summary="Host RVC stopped" if stopped else "Host RVC is still running",
                evidence_refs=(self._evidence("host-rvc-stop", f"{payload}\n"),),
                exit_code=0 if stopped else 1,
            )
        if command == ("host-rvc-preflight",):
            command = tuple(_rvc_preflight(wait=False))
        try:
            process_environment = os.environ.copy()
            process_environment.update(self._environment)
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                env=process_environment,
            )
            output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
            reference = self._evidence(
                f"command-{hashlib.sha256(repr(command).encode()).hexdigest()[:12]}",
                output,
            )
            summary = f"command completed with exit code {completed.returncode}"
            if completed.returncode == 0 and command[:3] == ("docker", "image", "inspect"):
                digest = completed.stdout.strip()
                summary = self._redact(
                    f"resolved image digest: {digest[:240]}" if digest else summary
                )
            elif completed.returncode != 0 and command[:3] == ("docker", "compose", "pull"):
                lowered = output.casefold()
                if "unauthorized" in lowered or "denied" in lowered:
                    summary = "image pull was denied; authenticate with 'docker login ghcr.io'"
            return self._observation_type(
                succeeded=completed.returncode == 0,
                summary=summary,
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
        except OSError as exc:
            reference = self._evidence("command-error", f"{type(exc).__name__}: {exc}\n")
            return self._observation_type(
                succeeded=False,
                summary=f"command could not start: {type(exc).__name__}",
                evidence_refs=(reference,),
            )

    def check_http(self, target: str, *, timeout_seconds: float):
        requires_authentication = target == "http://localhost/ready"
        invalid_access_token = any(character in self._access_token for character in "\r\n")
        if requires_authentication and (not self._access_token or invalid_access_token):
            reference = self._evidence(
                "http-auth-configuration",
                "ANIMETTA_ACCESS_TOKEN is unavailable or invalid\n",
            )
            return self._observation_type(
                succeeded=False,
                summary="ANIMETTA_ACCESS_TOKEN is required and must be a valid header value",
                evidence_refs=(reference,),
            )

        headers = (
            {"Authorization": f"Bearer {self._access_token}"} if requires_authentication else {}
        )
        request = urllib.request.Request(target, headers=headers)
        deadline = time.monotonic() + timeout_seconds
        last_error = "no response"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
                    body = response.read().decode("utf-8", errors="replace")
                    healthy = response.status == 200 and _valid_http_body(target, body)
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
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code in {401, 403}:
                    break
            except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
                last_error = type(exc).__name__
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


def _build_command_digest(
    command: tuple[str, ...],
    *,
    environment: dict[str, str],
    input_fingerprint: str,
) -> str:
    material = json.dumps(
        {
            "command": command,
            "environment": {
                "ANIMETTA_IMAGE": environment["ANIMETTA_IMAGE"],
                "ANIMETTA_PROFILE": environment["ANIMETTA_PROFILE"],
            },
            "input_fingerprint": input_fingerprint,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(material).hexdigest()


def _bounded_input_fingerprint(
    operation: str,
    *,
    image: str | None,
    profile: str,
) -> str:
    parts = [
        operation.encode(),
        profile.encode(),
        Path(__file__).read_bytes(),
        (ROOT / "tooling" / "execution_feedback" / "lifecycle.py").read_bytes(),
    ]
    if image is not None:
        parts.append(image.encode())
    material = b"\0".join(parts)
    return hashlib.sha256(material).hexdigest()


def _step_reuse_fingerprint(input_fingerprint: str, step_id: str) -> str:
    return hashlib.sha256(f"{input_fingerprint}:{step_id}".encode()).hexdigest()


def _build_lease_id(run_id: str, command_digest: str) -> str:
    """Scope the BuildKit lease to one run and one exact build invocation."""

    return f"{run_id}-animetta-build-{command_digest}"


def _allows_passed_checkpoint_reuse(operation: str, *, image: str | None) -> bool:
    return not (operation == "anima-deploy" and image == f"{GHCR_ANIMETTA_IMAGE}:main")


async def run_bounded_operation(
    operation: str,
    *,
    run_id: str,
    artifacts_root: Path,
    image: str | None = None,
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

    if operation != "anima-deploy" and image is not None:
        raise ValueError("--image is only valid with anima-deploy")
    selected_image = _validate_deploy_image(image or "") if operation == "anima-deploy" else None
    runtime_environment = _compose_environment(
        image=selected_image or LOCAL_ANIMETTA_IMAGE,
    )
    input_fingerprint = _bounded_input_fingerprint(
        operation,
        image=selected_image,
        profile=runtime_environment["ANIMETTA_PROFILE"],
    )
    build_command_digest = _build_command_digest(
        _ANIMETTA_BUILD_COMMAND,
        environment=runtime_environment,
        input_fingerprint=input_fingerprint,
    )
    build_lease_id = _build_lease_id(run_id, build_command_digest)
    frozen = freeze_lifecycle_plan(
        operation,
        input_fingerprint=input_fingerprint,
        run_id=run_id,
        image=selected_image,
    )
    store = IterationPlanStore(artifacts_root)
    store.write_plan(frozen.plan)
    run_root = artifacts_root.resolve() / run_id
    build_log = f"{run_id}/animetta-build.log"
    build_driver = LeasedSubprocessBuildDriver(
        workspace_root=ROOT,
        artifacts_root=artifacts_root.resolve(),
        receipt_path=run_root / "animetta-build-receipt.json",
        environment=runtime_environment,
    )
    build_controller = BuildStepController(
        lease_manager=LeaseManager(store),
        driver=build_driver,
        run_id=run_id,
        owner="lifecycle-worker",
        lease_id=build_lease_id,
        command=_ANIMETTA_BUILD_COMMAND,
        command_digest=build_command_digest,
        log_path=build_log,
    )
    executor = LifecycleStepExecutor(
        driver=_SystemLifecycleDriver(
            evidence_root=run_root / "evidence",
            environment=runtime_environment,
            access_token=_animetta_access_token() if operation == "anima-deploy" else None,
        ),
        build_controller=build_controller,
    )

    for step_contract, step_spec in zip(frozen.steps, frozen.plan.steps, strict=True):
        recovered = store.recover_latest_result(run_id, step_contract.id)
        reuse_fingerprint = _step_reuse_fingerprint(
            frozen.plan.input_fingerprint,
            step_contract.id,
        )
        checkpoint = store.read_checkpoint(run_id, step_contract.id)
        if (
            _allows_passed_checkpoint_reuse(operation, image=selected_image)
            and recovered.result is not None
            and recovered.result.status is FeedbackStatus.PASSED
            and checkpoint is not None
            and checkpoint.reuse_fingerprint == reuse_fingerprint
        ):
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
    parser.add_argument("--image", type=_image_argument)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=ROOT / "artifacts" / "iteration-plans",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.operation == "anima-deploy" and args.image is None:
        parser.error("anima-deploy requires --image")
    if args.operation != "anima-deploy" and args.image is not None:
        parser.error("--image is only valid with anima-deploy")
    run_id = args.run_id or f"{args.operation}-{uuid.uuid4().hex[:12]}"
    invocation = {"run_id": run_id, "mode": "bounded-feedback"}
    if args.image is not None:
        invocation["image"] = args.image
    print(json.dumps(invocation, sort_keys=True))
    return asyncio.run(
        run_bounded_operation(
            args.operation,
            run_id=run_id,
            artifacts_root=args.artifacts_root,
            image=args.image,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
