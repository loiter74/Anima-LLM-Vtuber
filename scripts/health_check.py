#!/usr/bin/env python3
from __future__ import annotations

"""Repository health gate runner for local and CI use."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DEFAULT_SUMMARY_FILE = ROOT / "artifacts" / "health" / "latest.json"
MAX_GATE_OUTPUT_CHARS = 4000

HEALTH_PASS = "pass"
HEALTH_DEGRADED = "degraded"
HEALTH_FAIL = "fail"
HEALTH_STATUSES = (HEALTH_PASS, HEALTH_DEGRADED, HEALTH_FAIL)
PROFILES = ("quick", "affected", "full", "docker")

CANONICAL_PYTHON = (3, 13)

REQUIRED_PYTHON_MODULES = ("pytest", "yaml", "starlette", "prometheus_client")
REQUIRED_PYTEST_PLUGIN_MODULES = {
    "pytest": "pytest",
    "pytest-asyncio": "pytest_asyncio",
    "pytest-cov": "pytest_cov",
    "pytest-timeout": "pytest_timeout",
    "pytest-xdist": "xdist",
}

ACCEPTED_WARNING_LEDGER: dict[str, dict[str, str]] = {
    "dependencies:frontend-audit-registry": {
        "owner": "project-health",
        "scope": "frontend/security",
        "reason": "Security advisory registry or mirror can be unreachable from local networks.",
        "remediation": "Retry with registry access or set ANIMETTA_PNPM to a pnpm command configured for the official npm registry.",
        "removal_condition": "Audit runs reliably against an approved advisory registry.",
    },
    "dependencies:pip-check": {
        "owner": "project-health",
        "scope": "python/dependencies",
        "reason": "Optional consistency signal can fail on local ML stacks without proving source breakage.",
        "remediation": "Resolve package conflicts in the active environment or rerun in a clean dev environment.",
        "removal_condition": "A pinned dev environment makes pip check deterministic.",
    },
}

SECRET_PATTERNS = [
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*[:=]\s*)([^\s]+)"
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)\b(Authorization:\s*Bearer\s+)([A-Za-z0-9._~+/=-]+)"),
        r"\1<redacted>",
    ),
]


@dataclass(frozen=True)
class Gate:
    id: str
    description: str
    command: tuple[str, ...]
    cwd: Path = ROOT
    required: bool = True
    profiles: tuple[str, ...] = ("full",)
    remediation: str = "Inspect the command output and fix the failing gate."
    timeout_s: int | None = None


@dataclass(frozen=True)
class PreflightCheck:
    id: str
    status: str
    message: str
    remediation: str = ""
    warning: dict[str, str] | None = None

    @property
    def ok(self) -> bool:
        return self.status != HEALTH_FAIL

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "remediation": self.remediation,
        }
        if self.warning:
            payload["warning"] = self.warning
        return payload


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    returncode: int
    output: str
    duration_s: float
    status: str
    remediation: str
    warnings: tuple[dict[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.status != HEALTH_FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.gate.id,
            "description": self.gate.description,
            "command": list(self.gate.command),
            "cwd": str(self.gate.cwd),
            "required": self.gate.required,
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 3),
            "status": self.status,
            "warnings": list(self.warnings),
            "remediation": self.remediation,
        }


def redact_output(output: str) -> str:
    redacted = output
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def accepted_warning(warning_id: str) -> dict[str, str]:
    base = ACCEPTED_WARNING_LEDGER.get(warning_id)
    if base is None:
        return {
            "id": warning_id,
            "owner": "project-health",
            "scope": "unclassified",
            "reason": "Unclassified warning emitted by health runner.",
            "remediation": "Classify this warning or fix the underlying cause.",
            "removal_condition": "Warning no longer appears.",
        }
    return {"id": warning_id, **base}


def _version_text(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def _python_command() -> tuple[str, ...]:
    override = os.environ.get("ANIMETTA_PYTHON")
    if override:
        return tuple(shlex.split(override, posix=os.name != "nt"))

    candidates: list[tuple[str, ...]] = []
    if os.name == "nt":
        for path_candidate in (
            ROOT / ".venv" / "Scripts" / "python.exe",
            ROOT / "venv" / "Scripts" / "python.exe",
        ):
            if path_candidate.exists():
                candidates.append((str(path_candidate),))
        if shutil.which("py"):
            candidates.append(("py", "-3.13"))

    candidates.append((sys.executable,))
    for command_candidate in candidates:
        if _python_has_health_dependencies(command_candidate):
            return command_candidate

    return (sys.executable,)


@cache
def _python_has_health_dependencies(command: tuple[str, ...]) -> bool:
    probe = (
        *command,
        "-c",
        "; ".join(f"import {module}" for module in REQUIRED_PYTHON_MODULES),
    )
    try:
        completed = subprocess.run(
            probe,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _python(*args: str) -> tuple[str, ...]:
    return (*_python_command(), *args)


def _pnpm_command() -> tuple[str, ...]:
    override = os.environ.get("ANIMETTA_PNPM")
    if override:
        return tuple(shlex.split(override, posix=os.name != "nt"))

    pnpm_names = ("pnpm.cmd", "pnpm") if os.name == "nt" else ("pnpm",)
    for name in pnpm_names:
        executable = shutil.which(name)
        if executable:
            return (executable,)

    corepack_names = ("corepack.cmd", "corepack") if os.name == "nt" else ("corepack",)
    for name in corepack_names:
        executable = shutil.which(name)
        if executable:
            return (executable, "pnpm")

    return ("pnpm.cmd",) if os.name == "nt" else ("pnpm",)


def _pnpm(*args: str) -> tuple[str, ...]:
    return (*_pnpm_command(), *args)


def _frontend_coverage_validation() -> None:
    package_json = Path("package.json")
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    if "test:coverage" not in scripts:
        raise SystemExit("frontend package.json is missing scripts.test:coverage")
    print(f"frontend coverage script: {scripts['test:coverage']}")


def _frontend_font_policy_validation() -> None:
    forbidden = ("fonts.googleapis", "fonts.gstatic", "Quicksand", "font-quicksand")
    files = (
        FRONTEND / "index.html",
        FRONTEND / "public" / "live.html",
        FRONTEND / "uno.config.ts",
    )
    violations: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            if term in text:
                violations.append(f"{path.relative_to(ROOT)} contains {term}")
    if violations:
        raise SystemExit("\n".join(violations))
    print("frontend font policy: no Google Fonts or Quicksand tokens in active files")


def _parse_pnpm_package_key(package_key: str) -> tuple[str, str] | None:
    key = package_key.lstrip("/").split("(", 1)[0]
    name, separator, version = key.rpartition("@")
    if not separator or not name or not version:
        return None
    return name, version.split("(", 1)[0]


def _collect_pnpm_lock_versions(lockfile: Path) -> dict[str, list[str]]:
    data = yaml.safe_load(lockfile.read_text(encoding="utf-8")) or {}
    versions: dict[str, set[str]] = {}
    for package_key in data.get("packages", {}):
        parsed = _parse_pnpm_package_key(str(package_key))
        if parsed is None:
            continue
        name, version = parsed
        versions.setdefault(name, set()).add(version)
    return {name: sorted(package_versions) for name, package_versions in sorted(versions.items())}


def _npm_bulk_advisories_from_lock(lockfile: Path) -> dict[str, Any]:
    package_versions = _collect_pnpm_lock_versions(lockfile)
    if not package_versions:
        raise RuntimeError(f"No package versions found in {lockfile}")

    body = json.dumps(package_versions).encode("utf-8")
    request = urllib.request.Request(
        "https://registry.npmjs.org/-/npm/v1/security/advisories/bulk",
        data=body,
        headers={
            "content-type": "application/json",
            "content-length": str(len(body)),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _frontend_audit_validation() -> None:
    command = (
        *_pnpm_command(),
        "audit",
        "--json",
        "--registry=https://registry.npmjs.org",
        "--audit-level=moderate",
    )
    completed = subprocess.run(
        command,
        cwd=FRONTEND,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=180,
    )
    output = completed.stdout.strip()
    if completed.returncode == 0:
        print(output or "pnpm audit: no vulnerabilities found")
        return

    if not _is_registry_failure(output):
        raise SystemExit(output or "pnpm audit failed")

    print("pnpm audit registry fetch failed; using official npm bulk advisory fallback")
    try:
        advisories = _npm_bulk_advisories_from_lock(FRONTEND / "pnpm-lock.yaml")
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        raise SystemExit(f"{output}\nFallback registry advisory fetch failed: {exc}") from exc

    affected = {name: items for name, items in advisories.items() if items}
    if affected:
        print(json.dumps(affected, ensure_ascii=False, indent=2))
        raise SystemExit("frontend audit found advisories at or above the configured audit level")
    print("frontend audit fallback: no advisories reported by official npm bulk endpoint")


def _docs_backend_framework_validation() -> None:
    files = (
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "architecture" / "overview.md",
        ROOT / "src" / "animetta" / "AGENTS.md",
    )
    violations: list[str] = []
    for path in files:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "fastapi" in line.lower():
                violations.append(f"{path.relative_to(ROOT)}:{line_no}: {line.strip()}")
    if violations:
        raise SystemExit("\n".join(violations))
    print("backend framework docs: Starlette + Socket.IO ASGI references are current")


def _docker_health_probe() -> None:
    with urllib.request.urlopen("http://localhost/health", timeout=10) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status != 200 or '"status":"ok"' not in body.replace(" ", ""):
            raise SystemExit(
                f"/health did not return status ok: HTTP {response.status} {body[:300]}"
            )
    print("docker health endpoint: /health returned HTTP 200 with status ok")


def _docker_frontend_probe() -> None:
    with urllib.request.urlopen("http://localhost", timeout=10) as response:
        if response.status != 200:
            raise SystemExit(f"frontend did not return HTTP 200: {response.status}")
    print("docker frontend endpoint: / returned HTTP 200")


def _docker_logs_probe() -> None:
    completed = subprocess.run(
        ("docker", "compose", "logs", "--no-color", "--tail=300", "animetta"),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=60,
    )
    output = completed.stdout
    if completed.returncode != 0:
        raise SystemExit(output.rstrip() or "docker compose logs failed")
    if "Traceback" in output or re.search(r"\b(ERROR|CRITICAL|FATAL)\b", output):
        raise SystemExit("docker logs contain Traceback or ERROR/CRITICAL/FATAL")
    print("docker logs: no Traceback or ERROR/CRITICAL/FATAL in recent animetta logs")


def build_gates(profile: str | None = "full") -> list[Gate]:
    gates = [
        Gate(
            "quality:affected",
            "Impact-aware verification for the current worktree",
            _python(
                "-m",
                "tooling.quality",
                "verify",
                "--tier",
                "affected",
                "--worktree",
            ),
            profiles=("affected",),
            remediation="Inspect the plan-hash evidence directory under artifacts/test-impact/.",
        ),
        Gate(
            "quality:full",
            "Full repository verification with a single backend coverage run",
            _python(
                "-m",
                "tooling.quality",
                "verify",
                "--tier",
                "full",
                "--worktree",
            ),
            profiles=("full",),
            remediation="Inspect the plan-hash evidence directory under artifacts/test-impact/.",
        ),
        Gate(
            "backend:ruff",
            "Backend lint",
            _python("-m", "ruff", "check", "src", "tests"),
            profiles=("quick",),
            remediation="Run ruff locally and fix reported lint violations.",
        ),
        Gate(
            "backend:mypy",
            "Backend type check",
            _python("-m", "mypy", "src/animetta", "--ignore-missing-imports"),
            profiles=("quick",),
            remediation="Fix type errors or document a targeted suppression.",
        ),
        Gate(
            "backend:pytest-collect",
            "Backend pytest collection",
            _python("-m", "pytest", "tests", "--collect-only", "-qq", "-o", "addopts="),
            profiles=("quick",),
            remediation="Fix import-time or collection failures before running the suite.",
        ),
        Gate(
            "frontend:coverage-script",
            "Frontend coverage script validation",
            _python(
                "-c", "from scripts.health_check import _frontend_coverage_validation as f; f()"
            ),
            FRONTEND,
            profiles=("full",),
            remediation="Add or repair frontend package.json scripts.test:coverage.",
        ),
        Gate(
            "frontend:font-policy",
            "Frontend OS-native font policy",
            _python(
                "-c", "from scripts.health_check import _frontend_font_policy_validation as f; f()"
            ),
            profiles=("quick", "full"),
            remediation="Remove Google Fonts and Quicksand references from active frontend files.",
        ),
        Gate(
            "docs:backend-framework",
            "Active docs backend framework wording",
            _python(
                "-c",
                "from scripts.health_check import _docs_backend_framework_validation as f; f()",
            ),
            profiles=("quick", "full"),
            remediation="Update active docs to say Starlette + Socket.IO ASGI, not FastAPI.",
        ),
        Gate(
            "events:validate",
            "Socket.IO event validation",
            _python("scripts/validate-events.py"),
            profiles=("quick",),
            remediation="Fix event schema drift reported by scripts/validate-events.py.",
        ),
        Gate(
            "dependencies:pip-check",
            "Python dependency consistency",
            _python("-m", "pip", "check"),
            required=False,
            profiles=("full",),
            remediation=ACCEPTED_WARNING_LEDGER["dependencies:pip-check"]["remediation"],
        ),
        Gate(
            "dependencies:frontend-audit",
            "Frontend npm audit against official registry",
            _python("-c", "from scripts.health_check import _frontend_audit_validation as f; f()"),
            FRONTEND,
            profiles=("full",),
            remediation="Fix confirmed advisories; retry registry/network failures before treating them as vulnerabilities.",
            timeout_s=180,
        ),
        Gate(
            "docker:compose-config",
            "Docker compose config validation",
            ("docker", "compose", "config", "--quiet"),
            profiles=("docker",),
            remediation="Fix docker-compose.yml syntax or unavailable compose configuration.",
        ),
        Gate(
            "docker:health-endpoint",
            "Docker /health readiness probe",
            _python("-c", "from scripts.health_check import _docker_health_probe as f; f()"),
            profiles=("docker",),
            remediation="Start services with the Docker startup protocol, then retry after /health is ready.",
        ),
        Gate(
            "docker:frontend-endpoint",
            "Docker frontend HTTP probe",
            _python("-c", "from scripts.health_check import _docker_frontend_probe as f; f()"),
            profiles=("docker",),
            remediation="Start services with the Docker startup protocol and verify nginx/frontend routing.",
        ),
        Gate(
            "docker:logs-clean",
            "Docker runtime log scan",
            _python("-c", "from scripts.health_check import _docker_logs_probe as f; f()"),
            profiles=("docker",),
            remediation="Inspect docker compose logs and fix Traceback or ERROR-level runtime failures.",
        ),
    ]
    if profile is None:
        return gates
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    return [gate for gate in gates if profile in gate.profiles]


def _run_json_python_probe(command: tuple[str, ...], code: str) -> dict[str, Any]:
    completed = subprocess.run(
        (*command, "-c", code),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "python probe failed")
    return json.loads(completed.stdout)


def check_python_runtime() -> PreflightCheck:
    command = _python_command()
    try:
        info = _run_json_python_probe(
            command,
            "import json, sys; print(json.dumps({'major': sys.version_info.major, 'minor': sys.version_info.minor, 'micro': sys.version_info.micro, 'executable': sys.executable}))",
        )
    except (OSError, subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        return PreflightCheck(
            "python:runtime",
            HEALTH_FAIL,
            f"Unable to inspect Python runtime using {' '.join(command)}: {exc}",
            "Install Python 3.13 or set ANIMETTA_PYTHON to a working interpreter.",
        )

    version = (int(info["major"]), int(info["minor"]))
    version_label = f"{info['major']}.{info['minor']}.{info['micro']}"
    if version == CANONICAL_PYTHON:
        return PreflightCheck(
            "python:runtime",
            HEALTH_PASS,
            f"Python {version_label} matches canonical {_version_text(CANONICAL_PYTHON)} baseline.",
        )
    return PreflightCheck(
        "python:runtime",
        HEALTH_FAIL,
        f"Python {version_label} does not match canonical {_version_text(CANONICAL_PYTHON)}.",
        "Install Python 3.13 or set ANIMETTA_PYTHON to a Python 3.13 interpreter.",
    )


def check_pytest_plugins() -> PreflightCheck:
    module_json = json.dumps(REQUIRED_PYTEST_PLUGIN_MODULES)
    command = _python_command()
    code = (
        "import importlib.util, json; "
        f"mods = {module_json!r}; "
        "mods = json.loads(mods); "
        "missing = [pkg for pkg, mod in mods.items() if importlib.util.find_spec(mod) is None]; "
        "print(json.dumps({'missing': missing}))"
    )
    try:
        info = _run_json_python_probe(command, code)
    except (OSError, subprocess.SubprocessError, RuntimeError, json.JSONDecodeError) as exc:
        return PreflightCheck(
            "pytest:plugins",
            HEALTH_FAIL,
            f"Unable to inspect pytest plugins: {exc}",
            "Install dev dependencies with: pip install -r requirements-dev.txt",
        )
    missing = list(info.get("missing", []))
    if missing:
        return PreflightCheck(
            "pytest:plugins",
            HEALTH_FAIL,
            f"Missing pytest plugin(s): {', '.join(missing)}",
            "Install dev dependencies with: pip install -r requirements-dev.txt",
        )
    return PreflightCheck(
        "pytest:plugins", HEALTH_PASS, "All configured pytest plugins are installed."
    )


def check_pnpm_toolchain() -> PreflightCheck:
    command = _pnpm_command()
    try:
        completed = subprocess.run(
            (*command, "--version"),
            cwd=FRONTEND,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return PreflightCheck(
            "frontend:pnpm",
            HEALTH_FAIL,
            f"Unable to run pnpm command {' '.join(command)}: {exc}",
            "Install pnpm or set ANIMETTA_PNPM. On Windows, run Corepack from an elevated shell if shim creation is blocked.",
        )
    if completed.returncode == 0:
        return PreflightCheck(
            "frontend:pnpm",
            HEALTH_PASS,
            f"pnpm is available: {completed.stdout.strip()}",
        )
    return PreflightCheck(
        "frontend:pnpm",
        HEALTH_FAIL,
        f"pnpm command failed: {completed.stdout.strip()}",
        "Install pnpm or set ANIMETTA_PNPM. On Windows, run Corepack from an elevated shell if shim creation is blocked.",
    )


def check_docker_toolchain() -> PreflightCheck:
    try:
        completed = subprocess.run(
            ("docker", "--version"),
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return PreflightCheck(
            "docker:cli",
            HEALTH_FAIL,
            f"Unable to run docker: {exc}",
            "Install Docker Desktop and ensure docker is on PATH.",
        )
    if completed.returncode == 0:
        return PreflightCheck("docker:cli", HEALTH_PASS, completed.stdout.strip())
    return PreflightCheck(
        "docker:cli",
        HEALTH_FAIL,
        completed.stdout.strip() or "docker --version failed",
        "Install Docker Desktop and ensure docker is on PATH.",
    )


def check_registry_reachability() -> PreflightCheck:
    try:
        with urllib.request.urlopen("https://registry.npmjs.org/", timeout=10) as response:
            if 200 <= response.status < 400:
                return PreflightCheck(
                    "dependencies:frontend-audit-registry",
                    HEALTH_PASS,
                    "Official npm registry is reachable.",
                )
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        warning = accepted_warning("dependencies:frontend-audit-registry")
        return PreflightCheck(
            "dependencies:frontend-audit-registry",
            HEALTH_DEGRADED,
            f"Official npm registry is not reachable: {exc}",
            warning["remediation"],
            warning,
        )
    warning = accepted_warning("dependencies:frontend-audit-registry")
    return PreflightCheck(
        "dependencies:frontend-audit-registry",
        HEALTH_DEGRADED,
        "Official npm registry returned an unexpected response.",
        warning["remediation"],
        warning,
    )


def run_preflight(gates: Sequence[Gate]) -> list[PreflightCheck]:
    gate_ids = {gate.id for gate in gates}
    checks = [check_python_runtime()]
    if any(
        gate_id.startswith("backend:pytest") or gate_id in {"backend:tests", "backend:coverage"}
        for gate_id in gate_ids
    ):
        checks.append(check_pytest_plugins())
    if any(
        gate_id.startswith("frontend:") or gate_id == "dependencies:frontend-audit"
        for gate_id in gate_ids
    ):
        checks.append(check_pnpm_toolchain())
    if any(gate_id.startswith("docker:") for gate_id in gate_ids):
        checks.append(check_docker_toolchain())
    if "dependencies:frontend-audit" in gate_ids:
        checks.append(check_registry_reachability())
    return checks


def _is_registry_failure(output: str) -> bool:
    lowered = output.lower()
    return any(
        term in lowered
        for term in (
            "econnrefused",
            "enotfound",
            "etimedout",
            "fetch failed",
            "network",
            "registry.npm",
            "advisories",
        )
    )


def _classify_gate(
    gate: Gate, returncode: int, output: str
) -> tuple[str, str, tuple[dict[str, str], ...]]:
    if returncode == 0:
        return HEALTH_PASS, "", ()
    if (
        gate.id == "dependencies:frontend-audit"
        and "frontend audit found advisories" in output.lower()
    ):
        return HEALTH_FAIL, gate.remediation, ()
    if gate.id == "dependencies:frontend-audit" and _is_registry_failure(output):
        warning = accepted_warning("dependencies:frontend-audit-registry")
        return HEALTH_DEGRADED, warning["remediation"], (warning,)
    if not gate.required:
        warning = accepted_warning(gate.id)
        return HEALTH_DEGRADED, gate.remediation, (warning,)
    return HEALTH_FAIL, gate.remediation, ()


def run_gate(gate: Gate) -> GateResult:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}"
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{env['PYTHONPATH']}{os.pathsep}{existing_pythonpath}"

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            gate.command,
            cwd=gate.cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=gate.timeout_s,
        )
        returncode = completed.returncode
        output = redact_output(completed.stdout)
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        output = redact_output(str(exc))
    except OSError as exc:
        returncode = 127
        output = redact_output(str(exc))

    duration_s = time.perf_counter() - started
    status, remediation, warnings = _classify_gate(gate, returncode, output)
    return GateResult(
        gate=gate,
        returncode=returncode,
        output=output,
        duration_s=duration_s,
        status=status,
        remediation=remediation,
        warnings=warnings,
    )


def run_gates(gates: Sequence[Gate]) -> list[GateResult]:
    results: list[GateResult] = []
    for gate in gates:
        print(f"\n==> {gate.id}: {gate.description}")
        result = run_gate(gate)
        results.append(result)
        if result.output.strip():
            output = result.output.rstrip()
            if len(output) > MAX_GATE_OUTPUT_CHARS:
                output = f"{output[:MAX_GATE_OUTPUT_CHARS]}\n... <gate output truncated>"
            print(output)
        print(f"<== {gate.id}: {result.status.upper()} ({result.duration_s:.1f}s)")
        if result.remediation and result.status != HEALTH_PASS:
            print(f"    remediation: {result.remediation}")
    return results


def overall_status(preflight: Sequence[PreflightCheck], gates: Sequence[GateResult]) -> str:
    statuses = [check.status for check in preflight] + [result.status for result in gates]
    if any(status == HEALTH_FAIL for status in statuses):
        return HEALTH_FAIL
    if any(status == HEALTH_DEGRADED for status in statuses):
        return HEALTH_DEGRADED
    return HEALTH_PASS


def build_summary(
    profile: str, preflight: Sequence[PreflightCheck], gates: Sequence[GateResult]
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT),
        "profile": profile,
        "status": overall_status(preflight, gates),
        "health_statuses": list(HEALTH_STATUSES),
        "python_policy": {
            "canonical": _version_text(CANONICAL_PYTHON),
        },
        "accepted_warning_ledger": [
            {"id": warning_id, **warning}
            for warning_id, warning in sorted(ACCEPTED_WARNING_LEDGER.items())
        ],
        "preflight": [check.to_dict() for check in preflight],
        "gates": [result.to_dict() for result in gates],
    }


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List gates without running them")
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default="full",
        help="Health profile to run when --only is not supplied.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run only a gate id. May be supplied multiple times and ignores --profile filtering.",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        default=DEFAULT_SUMMARY_FILE,
        help="Write machine-readable health evidence to this JSON file.",
    )
    parser.add_argument(
        "--no-summary-file",
        action="store_true",
        help="Do not write a machine-readable summary file.",
    )
    parser.add_argument("--json", action="store_true", help="Print the summary JSON after running")
    return parser.parse_args(argv)


def _select_gates(args: argparse.Namespace) -> list[Gate]:
    if args.only:
        all_gates = build_gates(profile=None)
        selected = set(args.only)
        gates = [gate for gate in all_gates if gate.id in selected]
        missing = selected - {gate.id for gate in gates}
        if missing:
            raise ValueError(f"Unknown gate id(s): {', '.join(sorted(missing))}")
        return gates
    return build_gates(args.profile)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args(argv)
    try:
        gates = _select_gates(args)
    except ValueError as exc:
        print(str(exc))
        return 2

    if args.list:
        for gate in gates:
            required = "required" if gate.required else "advisory"
            profiles = ",".join(gate.profiles)
            print(f"{gate.id}\t{required}\t{profiles}\t{gate.description}")
        return 0

    print(f"Health profile: {args.profile if not args.only else 'custom'}")
    print("Preflight:")
    preflight = run_preflight(gates)
    for check in preflight:
        print(f"- {check.id}: {check.status.upper()} - {check.message}")
        if check.remediation and check.status != HEALTH_PASS:
            print(f"  remediation: {check.remediation}")

    preflight_failed = any(not check.ok for check in preflight)
    results: list[GateResult] = []
    if preflight_failed:
        print("\nPreflight failed; gates were not run.")
    else:
        results = run_gates(gates)

    summary = build_summary(args.profile if not args.only else "custom", preflight, results)
    if not args.no_summary_file:
        write_summary(args.summary_file, summary)
        print(f"\nHealth evidence written to {args.summary_file}")
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    status = summary["status"]
    if status == HEALTH_FAIL:
        print("\nProject health: FAIL")
        return 1
    if status == HEALTH_DEGRADED:
        print("\nProject health: DEGRADED")
        return 0
    print("\nProject health: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
