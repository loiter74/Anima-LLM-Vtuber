from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from .manifest import LoadedCatalog
from .models import (
    Capability,
    ResultStatus,
    Runner,
    VerificationGroup,
    VerificationResult,
)


def build_argv(
    group: VerificationGroup,
    *,
    python_executable: str = sys.executable,
    npm_executable: str = "npm",
    pnpm_executable: str = "pnpm",
    docker_executable: str = "docker",
) -> list[str]:
    if group.runner is Runner.RUFF:
        return [python_executable, "-m", "ruff", "check", *group.targets, *group.args]
    if group.runner is Runner.RUFF_FORMAT:
        return [python_executable, "-m", "ruff", "format", *group.args, *group.targets]
    if group.runner is Runner.MYPY:
        return [python_executable, "-m", "mypy", *group.targets, *group.args]
    if group.runner is Runner.VULTURE:
        return [python_executable, "-m", "vulture", *group.targets, *group.args]
    if group.runner is Runner.PYTEST:
        return [python_executable, "-m", "pytest", *group.targets, *group.args]
    if group.runner is Runner.PYTHON:
        assert group.entrypoint is not None
        return [python_executable, group.entrypoint, *group.args]
    if group.runner is Runner.NPM:
        return [
            python_executable,
            "-m",
            "tooling.quality.npm_runner",
            "--npm",
            npm_executable,
            "--",
            *group.args,
        ]
    if group.runner is Runner.PNPM:
        return [pnpm_executable, *group.args]
    if group.runner is Runner.VITEST:
        return [pnpm_executable, "exec", "vitest", *group.args, *group.targets]
    if group.runner is Runner.PLAYWRIGHT:
        if group.entrypoint is not None:
            return [pnpm_executable, "exec", "node", group.entrypoint, *group.args]
        return [pnpm_executable, "exec", "playwright", *group.args]
    if group.runner is Runner.DOCKER:
        return [docker_executable, *group.args]
    raise ValueError(f"unsupported runner: {group.runner}")


def detect_capabilities(repo_root: str | Path) -> frozenset[Capability]:
    root = Path(repo_root)
    capabilities: set[Capability] = set()
    if shutil.which("docker"):
        capabilities.add(Capability.DOCKER)
    if shutil.which("pnpm") or shutil.which("pnpm.cmd"):
        playwright = root / "frontend" / "node_modules" / "playwright"
        if playwright.exists():
            capabilities.add(Capability.BROWSER)
    declared_text = os.environ.get("ANIMETTA_QUALITY_CAPABILITIES", "")
    declared_names = {name.strip() for name in declared_text.split(",") if name.strip()}
    allowed_declared = {Capability.NETWORK.value, Capability.GPU.value}
    invalid = declared_names - allowed_declared
    if invalid:
        raise ValueError(
            "ANIMETTA_QUALITY_CAPABILITIES may declare only network,gpu; "
            f"invalid values: {','.join(sorted(invalid))}"
        )
    capabilities.update(Capability(name) for name in declared_names)
    return frozenset(capabilities)


def _command_environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    entries = [str(root / "src"), str(root)]
    if existing:
        entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _redaction_environment(root: Path, command_env: dict[str, str]) -> dict[str, str]:
    """Include Compose-style dotenv secrets without injecting them into commands."""
    redaction_env = dict(command_env)
    dotenv = root / ".env"
    if not dotenv.is_file():
        return redaction_env
    for raw_line in dotenv.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if not name or not value:
            continue
        redaction_name = name if name not in redaction_env else f"DOTENV_{name}"
        redaction_env[redaction_name] = value
    return redaction_env


def _redact_output(output: str, env: dict[str, str]) -> str:
    redacted = output
    sensitive_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    candidates = sorted(
        (
            (name, value)
            for name, value in env.items()
            if value
            and len(value) >= 6
            and any(marker in name.upper() for marker in sensitive_markers)
        ),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for name, value in candidates:
        redacted = redacted.replace(value, f"<redacted:{name}>")
    redacted = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*\s*[:=]\s*)([^\s]+)",
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(Authorization:\s*Bearer\s+)([A-Za-z0-9._~+/=-]+)",
        r"\1<redacted>",
        redacted,
    )
    return redacted


def _timeout_output(exc: subprocess.TimeoutExpired, env: dict[str, str]) -> str:
    chunks: list[str] = []
    for value in (exc.stdout, exc.stderr):
        if isinstance(value, bytes):
            chunks.append(value.decode("utf-8", errors="replace"))
        elif value:
            chunks.append(value)
    return _redact_output("\n".join(chunks), env)


def _existing_artifacts(root: Path, group: VerificationGroup) -> tuple[str, ...]:
    return tuple(artifact for artifact in group.artifacts if (root / artifact).exists())


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        return
    try:
        kill_process_group = getattr(os, "killpg")
        kill_process_group(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            with suppress(ProcessLookupError):
                kill_process_group(process.pid, getattr(signal, "SIGKILL"))


def _joined_output(stdout: str | None, stderr: str | None, env: dict[str, str]) -> str:
    return _redact_output(
        "\n".join(part for part in (stdout, stderr) if part),
        env,
    )


def run_group(
    loaded: LoadedCatalog,
    group_id: str,
    *,
    plan_hash: str,
    repo_root: str | Path,
    available_capabilities: frozenset[Capability] | None = None,
    cancellation_event: threading.Event | None = None,
    targets_override: tuple[str, ...] | None = None,
    args_override: tuple[str, ...] | None = None,
    timeout_seconds_override: int | None = None,
    progress_callback: Callable[[float], None] | None = None,
    progress_interval_seconds: float = 60.0,
) -> VerificationResult:
    if progress_interval_seconds <= 0:
        raise ValueError("progress interval must be positive")
    if group_id not in loaded.catalog.groups:
        raise KeyError(f"unknown verification group: {group_id}")
    source_group = loaded.catalog.groups[group_id]
    updates: dict[str, object] = {}
    if targets_override is not None:
        updates["targets"] = targets_override
    if args_override is not None:
        updates["args"] = args_override
    if timeout_seconds_override is not None:
        if timeout_seconds_override < 1 or timeout_seconds_override > 240:
            raise ValueError("bounded group timeout must be in [1, 240]")
        updates["timeout_seconds"] = timeout_seconds_override
    # The catalog has already validated repository paths. Runtime pytest node IDs are
    # opaque selectors and may legitimately contain escaped backslashes (for example
    # ``\\u4f60``); re-running repository-path normalization would corrupt them.
    group = source_group.model_copy(update=updates)
    root = Path(repo_root).resolve()
    available = (
        detect_capabilities(root) if available_capabilities is None else available_capabilities
    )
    missing = sorted(capability.value for capability in group.capabilities - available)
    if missing:
        status = ResultStatus.BLOCKED if group.required else ResultStatus.SKIPPED
        return VerificationResult(
            group_id=group_id,
            required=group.required,
            status=status,
            exit_code=None,
            duration_seconds=0,
            failure_kind="capability",
            plan_hash=plan_hash,
            manifest_hash=loaded.manifest_hash,
            remediation=f"Install or enable required capabilities: {', '.join(missing)}",
        )

    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm") or "pnpm"
    docker = shutil.which("docker") or "docker"
    argv = build_argv(
        group,
        python_executable=sys.executable,
        npm_executable=npm,
        pnpm_executable=pnpm,
        docker_executable=docker,
    )
    command_env = _command_environment(root)
    redaction_env = _redaction_environment(root, command_env)
    cancellation = cancellation_event or threading.Event()
    started = time.perf_counter()
    try:
        popen_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(
            argv,
            cwd=root / group.cwd,
            env=command_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            **popen_kwargs,
        )
        deadline = started + group.timeout_seconds
        next_progress = started + progress_interval_seconds
        stdout = ""
        stderr = ""
        while True:
            if cancellation.is_set():
                _terminate_process_tree(process)
                stdout, stderr = process.communicate()
                duration = time.perf_counter() - started
                return VerificationResult(
                    group_id=group_id,
                    required=group.required,
                    status=ResultStatus.CANCELLED,
                    exit_code=None,
                    duration_seconds=duration,
                    run_seconds=duration,
                    failure_kind="cancelled",
                    artifacts=_existing_artifacts(root, group),
                    plan_hash=plan_hash,
                    manifest_hash=loaded.manifest_hash,
                    output=_joined_output(stdout, stderr, redaction_env),
                    remediation="Cancelled during execution",
                )
            now = time.perf_counter()
            if progress_callback is not None and now >= next_progress:
                try:
                    progress_callback(now - started)
                except Exception as exc:  # noqa: BLE001 - converted to evidence
                    _terminate_process_tree(process)
                    stdout, stderr = process.communicate()
                    duration = time.perf_counter() - started
                    return VerificationResult(
                        group_id=group_id,
                        required=group.required,
                        status=ResultStatus.FAILED,
                        exit_code=None,
                        duration_seconds=duration,
                        run_seconds=duration,
                        failure_kind="feedback-publication",
                        artifacts=_existing_artifacts(root, group),
                        plan_hash=plan_hash,
                        manifest_hash=loaded.manifest_hash,
                        output=_joined_output(stdout, stderr, redaction_env),
                        remediation=(
                            f"Unable to persist progress feedback: {type(exc).__name__}: {exc}"
                        ),
                    )
                while next_progress <= now:
                    next_progress += progress_interval_seconds
            remaining = deadline - now
            if remaining <= 0:
                _terminate_process_tree(process)
                stdout, stderr = process.communicate()
                duration = time.perf_counter() - started
                return VerificationResult(
                    group_id=group_id,
                    required=group.required,
                    status=ResultStatus.FAILED,
                    exit_code=None,
                    duration_seconds=duration,
                    run_seconds=duration,
                    failure_kind="timeout",
                    artifacts=_existing_artifacts(root, group),
                    plan_hash=plan_hash,
                    manifest_hash=loaded.manifest_hash,
                    output=_joined_output(stdout, stderr, redaction_env),
                    remediation=f"Group exceeded timeout of {group.timeout_seconds} seconds",
                )
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        duration = time.perf_counter() - started
        output = _joined_output(stdout, stderr, redaction_env)
        return VerificationResult(
            group_id=group_id,
            required=group.required,
            status=(ResultStatus.PASSED if process.returncode == 0 else ResultStatus.FAILED),
            exit_code=process.returncode,
            duration_seconds=duration,
            run_seconds=duration,
            failure_kind=None if process.returncode == 0 else "process",
            artifacts=_existing_artifacts(root, group),
            plan_hash=plan_hash,
            manifest_hash=loaded.manifest_hash,
            output=output,
        )
    except OSError as exc:
        return VerificationResult(
            group_id=group_id,
            required=group.required,
            status=ResultStatus.FAILED,
            exit_code=None,
            duration_seconds=time.perf_counter() - started,
            failure_kind="launch",
            plan_hash=plan_hash,
            manifest_hash=loaded.manifest_hash,
            remediation=(f"Unable to launch group in {group.cwd}: {type(exc).__name__}: {exc}"),
        )
    except KeyboardInterrupt:
        if "process" in locals():
            _terminate_process_tree(process)
        return VerificationResult(
            group_id=group_id,
            required=group.required,
            status=ResultStatus.CANCELLED,
            exit_code=None,
            duration_seconds=time.perf_counter() - started,
            failure_kind="cancelled",
            plan_hash=plan_hash,
            manifest_hash=loaded.manifest_hash,
        )


def collect_pytest_test_ids(
    loaded: LoadedCatalog,
    group_id: str,
    *,
    repo_root: str | Path,
    timeout_seconds: int = 120,
) -> tuple[str, ...]:
    if group_id not in loaded.catalog.groups:
        raise KeyError(f"unknown verification group: {group_id}")
    source_group = loaded.catalog.groups[group_id]
    collection_args: list[str] = []
    skip_next = False
    for arg in source_group.args:
        if skip_next:
            skip_next = False
            continue
        if arg in {"--cov", "--cov-report", "--cov-fail-under", "--cov-config"}:
            skip_next = True
            continue
        if arg.startswith(("--cov=", "--cov-report=", "--cov-fail-under=", "--cov-config=")):
            continue
        collection_args.append(arg)
    group = VerificationGroup.model_validate(
        {
            **source_group.model_dump(mode="python"),
            "args": tuple(collection_args),
        }
    )
    if group.runner is not Runner.PYTEST:
        return ()
    root = Path(repo_root).resolve()
    command_env = _command_environment(root)
    argv = build_argv(group, python_executable=sys.executable)
    argv.append("--collect-only")
    if not any(argument == "--quiet" or argument.startswith("-q") for argument in group.args):
        argv.append("-q")
    completed = subprocess.run(
        argv,
        cwd=root / group.cwd,
        env=command_env,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        output = _joined_output(
            completed.stdout,
            completed.stderr,
            _redaction_environment(root, command_env),
        )
        raise RuntimeError(f"pytest collection failed for {group_id}: {output}")
    node_ids = tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line and not line.lstrip().startswith(("=", "<"))
    )
    if not node_ids:
        raise RuntimeError(f"pytest collection returned no test IDs for {group_id}")
    return tuple(dict.fromkeys(node_ids))


def write_result(result: VerificationResult, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
