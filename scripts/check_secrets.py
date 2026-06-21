#!/usr/bin/env python3
"""Scan tracked configuration files for plaintext secrets.

The scanner reports locations only. It never prints secret values.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "secret_key",
    "sign_secret",
}

PLACEHOLDER_PATTERNS = (
    re.compile(r"^\$\{[A-Z0-9_]+(?::-[^}]*)?\}$"),
    re.compile(r"^your[_-].*[_-](key|token|password|secret)([_-]here)?$", re.IGNORECASE),
    re.compile(r"^(test|example|dummy|mock)[_-]?.*", re.IGNORECASE),
)


@dataclass(frozen=True)
class SecretFinding:
    path: Path
    key_path: str


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or normalized.endswith(("_api_key", "_token", "_password"))


def _is_allowed_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    return any(pattern.match(stripped) for pattern in PLACEHOLDER_PATTERNS)


def _walk_yaml(value: Any, path: Path, key_path: tuple[str, ...]) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key)
            nested_path = (*key_path, key)
            if _is_sensitive_key(key) and isinstance(nested, str) and not _is_allowed_value(nested):
                findings.append(SecretFinding(path=path, key_path=".".join(nested_path)))
            else:
                findings.extend(_walk_yaml(nested, path, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(_walk_yaml(nested, path, (*key_path, str(index))))
    return findings


def _scan_yaml(path: Path) -> list[SecretFinding]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if data is None:
        return []
    return _walk_yaml(data, path, ())


def find_plaintext_secrets(paths: list[Path]) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in paths:
        if path.suffix.lower() in {".yaml", ".yml"} and path.is_file():
            findings.extend(_scan_yaml(path))
    return findings


def format_findings(findings: list[SecretFinding]) -> str:
    if not findings:
        return "No plaintext secrets found."
    lines = ["Plaintext secret-like values found:"]
    for finding in findings:
        lines.append(f"- {finding.path}: {finding.key_path}")
    return "\n".join(lines)


def _default_paths(root: Path) -> list[Path]:
    config_dir = root / "config"
    return sorted([*config_dir.glob("*.yaml"), *config_dir.glob("*.yml")])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="YAML config files to scan")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    paths = args.paths or _default_paths(root)
    findings = find_plaintext_secrets(paths)
    print(format_findings(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
