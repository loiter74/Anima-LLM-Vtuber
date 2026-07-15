"""Validate every tracked operational source with a deterministic parser or analyzer."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

import yaml


class SourceKind(StrEnum):
    """Operational source categories covered by the repository gate."""

    DOCKERFILE = "dockerfile"
    SHELL = "shell"
    POWERSHELL = "powershell"
    BATCH = "batch"
    YAML = "yaml"
    JSON = "json"
    TOML = "toml"


@dataclass(frozen=True, slots=True)
class SourceViolation:
    """One actionable source-standard violation."""

    path: str
    message: str


_DOCKERFILE_INSTRUCTIONS = {
    "ADD",
    "ARG",
    "CMD",
    "COPY",
    "ENTRYPOINT",
    "ENV",
    "EXPOSE",
    "FROM",
    "HEALTHCHECK",
    "LABEL",
    "MAINTAINER",
    "ONBUILD",
    "RUN",
    "SHELL",
    "STOPSIGNAL",
    "USER",
    "VOLUME",
    "WORKDIR",
}
_WINDOWS_USER_PATH = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s\"]+")


def classify_path(path: PurePosixPath) -> SourceKind | None:
    """Classify a tracked path by operational source semantics."""

    name = path.name
    suffix = path.suffix.lower()
    if name == "Dockerfile" or name.startswith("Dockerfile."):
        return SourceKind.DOCKERFILE
    if suffix == ".sh":
        return SourceKind.SHELL
    if suffix == ".ps1":
        return SourceKind.POWERSHELL
    if suffix in {".bat", ".cmd"}:
        return SourceKind.BATCH
    if suffix in {".yaml", ".yml"}:
        return SourceKind.YAML
    if suffix == ".json":
        return SourceKind.JSON
    if suffix == ".toml":
        return SourceKind.TOML
    return None


def validate_source(path: PurePosixPath, content: str) -> list[SourceViolation]:
    """Run deterministic in-process validation for one operational source."""

    kind = classify_path(path)
    if kind is None:
        return []
    if kind is SourceKind.DOCKERFILE:
        return _validate_dockerfile(path, content)
    if kind is SourceKind.BATCH:
        return _validate_batch(path, content)
    if kind is SourceKind.YAML:
        return _validate_yaml(path, content)
    if kind is SourceKind.JSON:
        return _validate_json(path, content)
    if kind is SourceKind.TOML:
        return _validate_toml(path, content)
    return []


def _violation(path: PurePosixPath, message: str) -> SourceViolation:
    return SourceViolation(path=path.as_posix(), message=message)


def _validate_dockerfile(path: PurePosixPath, content: str) -> list[SourceViolation]:
    violations: list[SourceViolation] = []
    instructions: list[str] = []
    pending = ""

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        pending = f"{pending} {stripped}".strip()
        if stripped.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        instructions.append(pending)
        pending = ""

    if pending:
        violations.append(_violation(path, "Dockerfile ends with an unfinished continuation"))
        instructions.append(pending)
    if not instructions:
        return [*violations, _violation(path, "Dockerfile contains no instructions")]

    parsed = [instruction.split(maxsplit=1)[0].upper() for instruction in instructions]
    if parsed[0] not in {"ARG", "FROM"}:
        violations.append(_violation(path, "first Dockerfile instruction must be ARG or FROM"))
    if "FROM" not in parsed:
        violations.append(_violation(path, "Dockerfile must contain a FROM instruction"))
    for instruction in parsed:
        if instruction not in _DOCKERFILE_INSTRUCTIONS:
            violations.append(_violation(path, f"unknown Dockerfile instruction: {instruction}"))
    return violations


def _validate_batch(path: PurePosixPath, content: str) -> list[SourceViolation]:
    violations: list[SourceViolation] = []
    commands = [line.strip() for line in content.splitlines() if line.strip()]
    if not commands or commands[0].lower() != "@echo off":
        violations.append(_violation(path, "batch scripts must start with '@echo off'"))
    if _WINDOWS_USER_PATH.search(content):
        violations.append(_violation(path, "batch script contains a machine-specific user path"))
    return violations


def _validate_yaml(path: PurePosixPath, content: str) -> list[SourceViolation]:
    try:
        list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        return [_violation(path, f"invalid YAML: {exc}")]
    return []


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_json(path: PurePosixPath, content: str) -> list[SourceViolation]:
    try:
        json.loads(content, object_pairs_hook=_reject_duplicate_json_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        return [_violation(path, f"invalid JSON: {exc}")]
    return []


def _validate_toml(path: PurePosixPath, content: str) -> list[SourceViolation]:
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        return [_violation(path, f"invalid TOML: {exc}")]
    return []


def _tracked_operational_sources(root: Path) -> list[tuple[PurePosixPath, SourceKind]]:
    completed = subprocess.run(
        (
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ),
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {detail}")

    sources: list[tuple[PurePosixPath, SourceKind]] = []
    for raw_path in completed.stdout.decode("utf-8").split("\0"):
        if not raw_path:
            continue
        path = PurePosixPath(raw_path)
        if not (root / Path(path.as_posix())).is_file():
            continue
        kind = classify_path(path)
        if kind is not None:
            sources.append((path, kind))
    return sources


def _resolve_bash() -> str | None:
    configured = os.environ.get("ANIMETTA_BASH")
    if configured:
        return configured
    if os.name == "nt":
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        git_bash = program_files / "Git" / "bin" / "bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    return shutil.which("bash")


def _resolve_powershell() -> str | None:
    configured = os.environ.get("ANIMETTA_POWERSHELL")
    if configured:
        return configured
    return shutil.which("pwsh") or shutil.which("powershell")


def _run_external_syntax_checks(
    root: Path,
    sources: Sequence[tuple[PurePosixPath, SourceKind]],
) -> list[SourceViolation]:
    violations: list[SourceViolation] = []
    shell_paths = [path for path, kind in sources if kind is SourceKind.SHELL]
    powershell_paths = [path for path, kind in sources if kind is SourceKind.POWERSHELL]

    if shell_paths:
        bash = _resolve_bash()
        if bash is None:
            violations.append(
                SourceViolation(
                    path="<toolchain>",
                    message="bash is required to parse tracked shell scripts",
                )
            )
        else:
            for path in shell_paths:
                completed = subprocess.run(
                    (bash, "-n", str((root / Path(path.as_posix())).resolve())),
                    check=False,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                if completed.returncode != 0:
                    detail = completed.stdout.strip() or "bash -n failed"
                    violations.append(_violation(path, f"invalid shell syntax: {detail}"))

    if powershell_paths:
        powershell = _resolve_powershell()
        if powershell is None:
            violations.append(
                SourceViolation(
                    path="<toolchain>",
                    message="PowerShell is required to parse tracked .ps1 scripts",
                )
            )
            return violations
        parser = (
            "& { param($Path) $tokens = $null; $errors = $null; "
            "[System.Management.Automation.Language.Parser]::ParseFile($Path, "
            "[ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 } }"
        )
        for path in powershell_paths:
            completed = subprocess.run(
                (
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    parser,
                    str((root / Path(path.as_posix())).resolve()),
                ),
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if completed.returncode != 0:
                detail = completed.stdout.strip() or "PowerShell parser failed"
                violations.append(_violation(path, f"invalid PowerShell syntax: {detail}"))
    return violations


def check_repository(root: Path) -> tuple[list[SourceViolation], Counter[SourceKind]]:
    """Validate every tracked operational source under ``root``."""

    sources = _tracked_operational_sources(root)
    counts: Counter[SourceKind] = Counter(kind for _, kind in sources)
    violations: list[SourceViolation] = []
    for path, _kind in sources:
        disk_path = root / Path(path.as_posix())
        try:
            content = disk_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            violations.append(_violation(path, f"cannot read as UTF-8: {exc}"))
            continue
        violations.extend(validate_source(path, content))
    violations.extend(_run_external_syntax_checks(root, sources))
    return violations, counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate tracked sources without modifying them",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the operational-source contract."""

    args = _build_parser().parse_args(argv)
    if not args.check:
        raise SystemExit("--check is required; this command never rewrites source files")

    try:
        violations, counts = check_repository(args.root.resolve())
    except RuntimeError as exc:
        print(f"source standards: {exc}", file=sys.stderr)
        return 2

    summary = ", ".join(f"{kind.value}={counts[kind]}" for kind in SourceKind)
    if violations:
        for violation in violations:
            print(f"{violation.path}: {violation.message}", file=sys.stderr)
        print(f"source standards failed ({summary})", file=sys.stderr)
        return 1

    print(f"source standards passed ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
