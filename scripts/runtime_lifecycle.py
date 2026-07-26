"""Cross-platform lifecycle operations for persistent Qwen and Animetta."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOST_TTS_RUNTIME_ROOT = Path(r"D:\AnimaModelAuditions\qwen3-tts-1.7b-streaming-20260726")
HOST_TTS_PYTHON = HOST_TTS_RUNTIME_ROOT / "venv" / "Scripts" / "python.exe"
HOST_TTS_PID_FILE = HOST_TTS_RUNTIME_ROOT / "host-tts.pid.json"
HOST_TTS_LOG_FILE = HOST_TTS_RUNTIME_ROOT / "log" / "host-tts.log"
HOST_TTS_BASE_URL = "http://127.0.0.1:8767"
HOST_TTS_IDENTITY = {
    "provider": "qwen3-tts-gguf-host",
    "model": "Qwen3-TTS-1.7B-Base",
    "quantization": "talker=Q5_K,predictor=Q8_0,onnx=FP16",
    "voice": "tosaka-rin-cn",
    "runtime_commit": "0eb32e283ee46b86820c67843abb04cf12bc58d7",
    "sample_rate": 24000,
}

QWEN_COMPOSE = ["docker", "compose", "-f", "docker-compose.qwen.yml"]
SELFTEST_COMPOSE = [
    "docker",
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.selftest.yml",
]
OPERATIONS = (
    "qwen-build",
    "qwen-up",
    "qwen-deploy",
    "qwen-stop",
    "qwen-destroy",
    "host-tts-up",
    "host-tts-status",
    "host-tts-stop",
    "anima-up",
    "anima-selftest-up",
    "anima-down",
)


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


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


def _qwen_build_fingerprint() -> str:
    from tooling.quality.docker_plan import fingerprint_docker_scopes
    from tooling.quality.fingerprint import FingerprintContext
    from tooling.quality.manifest import load_catalog

    loaded = load_catalog(ROOT / "tooling" / "quality.yml")
    return fingerprint_docker_scopes(loaded.catalog, FingerprintContext(ROOT))["qwen-tts"]


def _qwen_build_command() -> list[str]:
    return [
        *QWEN_COMPOSE,
        "build",
        "--build-arg",
        f"QWEN_TTS_BUILD_FINGERPRINT={_qwen_build_fingerprint()}",
        "qwen-tts",
    ]


def run_operation(operation: str) -> None:
    """Execute one explicit lifecycle operation."""
    if operation == "qwen-build":
        _run(_qwen_build_command())
    elif operation == "qwen-up":
        _run(
            [
                *QWEN_COMPOSE,
                "up",
                "-d",
                "--no-build",
                "--no-recreate",
                "qwen-tts",
            ]
        )
        _run(_preflight(wait=True))
    elif operation == "qwen-deploy":
        _run(_qwen_build_command())
        _run(
            [
                *QWEN_COMPOSE,
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                "qwen-tts",
            ]
        )
        _run(_preflight(wait=True))
    elif operation == "qwen-stop":
        _run([*QWEN_COMPOSE, "stop", "qwen-tts"])
    elif operation == "qwen-destroy":
        _run([*QWEN_COMPOSE, "down", "--remove-orphans"])
    elif operation == "host-tts-up":
        _host_tts_up(best_effort=False)
    elif operation == "host-tts-status":
        print(json.dumps(_host_tts_status(), sort_keys=True))
    elif operation == "host-tts-stop":
        _host_tts_stop()
    elif operation == "anima-up":
        _host_tts_up(best_effort=True)
        _run(_preflight(wait=False))
        _run(["docker", "compose", "build", "animetta"])
        _run(["docker", "compose", "up", "-d", "--no-build", "animetta"])
    elif operation == "anima-selftest-up":
        _run(_preflight(wait=True))
        _run([*SELFTEST_COMPOSE, "build", "animetta"])
        _run([*SELFTEST_COMPOSE, "up", "-d", "--no-build", "animetta"])
    elif operation == "anima-down":
        _run(["docker", "compose", "down", "--remove-orphans"])
    else:
        raise ValueError(f"Unknown lifecycle operation: {operation}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_operation(args.operation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
