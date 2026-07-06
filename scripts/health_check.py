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
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
REQUIRED_PYTHON_MODULES = ("pytest", "yaml", "starlette", "prometheus_client")

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


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def redact_output(output: str) -> str:
    redacted = output
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _python_command() -> tuple[str, ...]:
    override = os.environ.get("ANIMETTA_PYTHON")
    if override:
        return tuple(shlex.split(override, posix=os.name != "nt"))

    candidates: list[tuple[str, ...]] = []
    if os.name == "nt":
        for candidate in (
            ROOT / ".venv" / "Scripts" / "python.exe",
            ROOT / "venv" / "Scripts" / "python.exe",
        ):
            if candidate.exists():
                candidates.append((str(candidate),))
        if shutil.which("py"):
            candidates.append(("py", "-3.13"))

    candidates.append((sys.executable,))
    for candidate in candidates:
        if _python_has_health_dependencies(candidate):
            return candidate

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


def _frontend_coverage_validation() -> str:
    package_json = Path("package.json")
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    if "test:coverage" not in scripts:
        raise SystemExit("frontend package.json is missing scripts.test:coverage")
    print(f"frontend coverage script: {scripts['test:coverage']}")


def build_gates() -> list[Gate]:
    pytest_base = (
        "-m",
        "pytest",
        "tests",
        "-q",
        "-o",
        "addopts=",
        "-m",
        "not slow and not integration",
        "--tb=short",
    )
    return [
        Gate("backend:ruff", "Backend lint", ("ruff", "check", "src", "tests")),
        Gate("backend:mypy", "Backend type check", ("mypy", "src", "--ignore-missing-imports")),
        Gate("backend:tests", "Backend tests", _python(*pytest_base)),
        Gate(
            "backend:coverage",
            "Backend coverage report",
            _python(
                *pytest_base,
                "--cov-report=term-missing",
                "--cov-fail-under=67",
                "--cov=src/animetta",
            ),
        ),
        Gate("frontend:typecheck", "Frontend type check", _pnpm("run", "typecheck"), FRONTEND),
        Gate("frontend:tests", "Frontend tests", _pnpm("run", "test:run"), FRONTEND),
        Gate("frontend:build", "Frontend production build", _pnpm("run", "build"), FRONTEND),
        Gate(
            "frontend:coverage-script",
            "Frontend coverage script validation",
            _python("-c", "from scripts.health_check import _frontend_coverage_validation as f; f()"),
            FRONTEND,
        ),
        Gate("events:validate", "Socket.IO event validation", _python("scripts/validate-events.py")),
        Gate(
            "docker:compose-gpu-config",
            "Docker compose GPU config validation",
            ("docker", "compose", "config"),
        ),
        Gate(
            "docker:compose-cpu-config",
            "Docker compose CPU config validation",
            ("docker", "compose", "-f", "docker-compose.cpu.yml", "config"),
        ),
        Gate("security:secrets", "Tracked config secret scan", _python("scripts/check_secrets.py")),
        Gate(
            "dependencies:pip-check",
            "Python dependency consistency",
            _python("-m", "pip", "check"),
            required=False,
        ),
        Gate(
            "dependencies:frontend-audit",
            "Frontend npm audit against official registry",
            _pnpm(
                "audit",
                "--json",
                "--registry=https://registry.npmjs.org",
                "--audit-level=moderate",
            ),
            FRONTEND,
            required=False,
        ),
        Gate("routes:smoke", "Lightweight ASGI route probes", _python("scripts/route_smoke.py")),
    ]


def run_gate(gate: Gate) -> GateResult:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}"
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{env['PYTHONPATH']}{os.pathsep}{existing_pythonpath}"

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
    )
    return GateResult(
        gate=gate,
        returncode=completed.returncode,
        output=redact_output(completed.stdout),
    )


def run_gates(gates: Sequence[Gate]) -> list[GateResult]:
    results: list[GateResult] = []
    for gate in gates:
        print(f"\n==> {gate.id}: {gate.description}")
        result = run_gate(gate)
        results.append(result)
        if result.output.strip():
            output = result.output.rstrip()
            if not gate.required and len(output) > 4000:
                output = f"{output[:4000]}\n... <advisory output truncated>"
            print(output)
        status = "PASS" if result.ok else "FAIL"
        print(f"<== {gate.id}: {status}")
    return results


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List gates without running them")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run only a gate id. May be supplied multiple times.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args(argv)
    gates = build_gates()

    if args.only:
        selected = set(args.only)
        gates = [gate for gate in gates if gate.id in selected]
        missing = selected - {gate.id for gate in gates}
        if missing:
            print(f"Unknown gate id(s): {', '.join(sorted(missing))}")
            return 2

    if args.list:
        for gate in gates:
            required = "required" if gate.required else "advisory"
            print(f"{gate.id}\t{required}\t{gate.description}")
        return 0

    results = run_gates(gates)
    failed_required = [
        result for result in results if result.gate.required and not result.ok
    ]
    if failed_required:
        print("\nFAILED required gates:")
        for result in failed_required:
            print(f"- {result.gate.id}")
        return 1

    print("\nAll required health gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
