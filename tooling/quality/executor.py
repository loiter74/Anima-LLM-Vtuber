from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

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
    pnpm_executable: str = "pnpm",
    docker_executable: str = "docker",
) -> list[str]:
    if group.runner is Runner.RUFF:
        return [python_executable, "-m", "ruff", "check", *group.targets, *group.args]
    if group.runner is Runner.MYPY:
        return [python_executable, "-m", "mypy", *group.targets, *group.args]
    if group.runner is Runner.PYTEST:
        return [python_executable, "-m", "pytest", *group.targets, *group.args]
    if group.runner is Runner.PYTHON:
        assert group.entrypoint is not None
        return [python_executable, group.entrypoint, *group.args]
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
    return tuple(
        artifact for artifact in group.artifacts if (root / artifact).exists()
    )


def run_group(
    loaded: LoadedCatalog,
    group_id: str,
    *,
    plan_hash: str,
    repo_root: str | Path,
    available_capabilities: frozenset[Capability] | None = None,
) -> VerificationResult:
    if group_id not in loaded.catalog.groups:
        raise KeyError(f"unknown verification group: {group_id}")
    group = loaded.catalog.groups[group_id]
    root = Path(repo_root).resolve()
    available = (
        detect_capabilities(root)
        if available_capabilities is None
        else available_capabilities
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

    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm") or "pnpm"
    docker = shutil.which("docker") or "docker"
    argv = build_argv(
        group,
        python_executable=sys.executable,
        pnpm_executable=pnpm,
        docker_executable=docker,
    )
    command_env = _command_environment(root)
    redaction_env = _redaction_environment(root, command_env)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=root / group.cwd,
            env=command_env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=group.timeout_seconds,
            shell=False,
        )
        duration = time.perf_counter() - started
        output = _redact_output(
            "\n".join(part for part in (completed.stdout, completed.stderr) if part),
            redaction_env,
        )
        return VerificationResult(
            group_id=group_id,
            required=group.required,
            status=(
                ResultStatus.PASSED if completed.returncode == 0 else ResultStatus.FAILED
            ),
            exit_code=completed.returncode,
            duration_seconds=duration,
            failure_kind=None if completed.returncode == 0 else "process",
            artifacts=_existing_artifacts(root, group),
            plan_hash=plan_hash,
            manifest_hash=loaded.manifest_hash,
            output=output,
        )
    except subprocess.TimeoutExpired as exc:
        return VerificationResult(
            group_id=group_id,
            required=group.required,
            status=ResultStatus.FAILED,
            exit_code=None,
            duration_seconds=time.perf_counter() - started,
            failure_kind="timeout",
            artifacts=_existing_artifacts(root, group),
            plan_hash=plan_hash,
            manifest_hash=loaded.manifest_hash,
            output=_timeout_output(exc, redaction_env),
            remediation=f"Group exceeded timeout of {group.timeout_seconds} seconds",
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
            remediation=(
                f"Unable to launch group in {group.cwd}: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
    except KeyboardInterrupt:
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


def write_result(result: VerificationResult, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
