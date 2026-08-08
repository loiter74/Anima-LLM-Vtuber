from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL_VERSION = "3.13"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_active_python_version_configuration_matches_canonical_pin() -> None:
    problems: list[str] = []
    version_file = ROOT / ".python-version"
    pinned_version = (
        version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    )
    if pinned_version != CANONICAL_VERSION:
        problems.append(
            f".python-version must contain {CANONICAL_VERSION!r}, found {pinned_version!r}"
        )

    required_fragments = {
        "pyproject.toml": (
            'requires-python = ">=3.13"',
            'python_version = "3.13"',
        ),
        "uv.lock": ('requires-python = ">=3.13"',),
        "Dockerfile": (
            "FROM python:3.13-slim-bookworm AS python-builder",
            "FROM python:3.13-slim-bookworm AS runtime",
        ),
        "docker-compose.cpu.yml": ("dockerfile: Dockerfile",),
        "observability/Dockerfile.notifier": ("FROM python:3.13-slim-bookworm",),
        "scripts/health_check.py": ("CANONICAL_PYTHON = (3, 13)",),
        "README.md": ("python-3.13",),
        "CONTRIBUTING.md": ("Python 3.13+",),
        "docs/development/project-health.md": ("Python 3.13",),
        "tests/AGENTS.md": ("Python 3.13",),
    }
    for relative_path, fragments in required_fragments.items():
        content = _read(relative_path)
        for fragment in fragments:
            if fragment not in content:
                problems.append(f"{relative_path} is missing {fragment!r}")

    for relative_path in (
        ".github/workflows/test.yml",
        ".github/workflows/deploy-zeabur.yml",
    ):
        if not (ROOT / relative_path).exists():
            continue
        content = _read(relative_path)
        setup_count = content.count("uses: actions/setup-python@v5")
        version_file_count = content.count("python-version-file: .python-version")
        if setup_count != version_file_count:
            problems.append(
                f"{relative_path} has {setup_count} setup-python steps but "
                f"{version_file_count} .python-version consumers"
            )

    forbidden_fragments = {
        "pyproject.toml": ('requires-python = ">=3.11"',),
        "uv.lock": ('requires-python = ">=3.11"',),
        ".github/workflows/test.yml": ("3.11", "3.12"),
        ".github/workflows/deploy-zeabur.yml": ("python-version:",),
        "Dockerfile": ("python:3.11", "python:3.12"),
        "docker-compose.cpu.yml": ("python:3.11", "python:3.12"),
        "observability/Dockerfile.notifier": ("python:3.11", "python:3.12"),
        "scripts/health_check.py": (
            "ACCEPTED_LOCAL_PYTHON_MIN",
            "DOCKER_PYTHON_EXCEPTION",
            '"python:runtime-degraded"',
        ),
        "requirements-local-ai.txt": ('python_version < "3.13"',),
        "README.md": ("python-3.11", "python-3.12"),
        "docs/development/project-health.md": ("Python 3.11", "Python 3.12"),
        "docs/demo/interview-demo.md": ("Python 3.12/3.13",),
        "tests/AGENTS.md": ("Python 3.12",),
    }
    for relative_path, fragments in forbidden_fragments.items():
        if not (ROOT / relative_path).exists():
            continue
        content = _read(relative_path)
        for fragment in fragments:
            if fragment in content:
                problems.append(f"{relative_path} still contains unsupported {fragment!r}")

    workflow_path = ROOT / ".github/workflows/test.yml"
    if workflow_path.exists():
        workflow = _read(".github/workflows/test.yml")
        if re.search(r"python-version:\s*\[", workflow):
            problems.append(".github/workflows/test.yml still defines a Python version matrix")

    assert not problems, "Python runtime policy drift:\n- " + "\n- ".join(problems)
