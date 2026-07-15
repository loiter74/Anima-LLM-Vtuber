from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest

from scripts import check_source_standards as standards


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Dockerfile", standards.SourceKind.DOCKERFILE),
        ("observability/Dockerfile.notifier", standards.SourceKind.DOCKERFILE),
        ("docker/entrypoint.sh", standards.SourceKind.SHELL),
        ("scripts/verify.ps1", standards.SourceKind.POWERSHELL),
        ("scripts/start.bat", standards.SourceKind.BATCH),
        ("config/animetta.yaml", standards.SourceKind.YAML),
        ("config/socket-events.json", standards.SourceKind.JSON),
        ("pyproject.toml", standards.SourceKind.TOML),
        (
            "src/animetta/tools/embedded.mjs",
            standards.SourceKind.MISPLACED_JAVASCRIPT,
        ),
        ("src/animetta/core/server.py", None),
    ],
)
def test_classify_path_covers_every_operational_source_kind(
    path: str,
    expected: standards.SourceKind | None,
) -> None:
    assert standards.classify_path(PurePosixPath(path)) is expected


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("config/broken.json", '{"missing": }'),
        ("config/broken.yaml", "key: [unterminated"),
        ("broken.toml", 'name = "unterminated'),
    ],
)
def test_structured_source_validation_reports_invalid_syntax(path: str, content: str) -> None:
    violations = standards.validate_source(PurePosixPath(path), content)

    assert violations
    assert violations[0].path == path


def test_dockerfile_validation_requires_a_complete_from_instruction() -> None:
    violations = standards.validate_source(
        PurePosixPath("Dockerfile"),
        "RUN echo before-stage\nFROM python:3.13-slim " + "\\",
    )

    messages = {violation.message for violation in violations}
    assert "first Dockerfile instruction must be ARG or FROM" in messages
    assert "Dockerfile ends with an unfinished continuation" in messages


def test_batch_validation_rejects_machine_specific_user_paths() -> None:
    violations = standards.validate_source(
        PurePosixPath("scripts/start.bat"),
        "@echo off\ncd /d C:\\Users\\someone\\Project\n",
    )

    assert any("machine-specific user path" in item.message for item in violations)


def test_python_source_tree_rejects_ungated_javascript() -> None:
    violations = standards.validate_source(
        PurePosixPath("src/animetta/tools/embedded.mjs"),
        "console.log('not in a JavaScript package')\n",
    )

    assert [item.message for item in violations] == [
        "JavaScript must live in a dedicated package with lint and format gates"
    ]


def test_valid_structured_and_batch_sources_have_no_violations() -> None:
    samples = {
        "config/ok.json": '{"enabled": true}\n',
        "config/ok.yaml": "enabled: true\n",
        "ok.toml": 'name = "animetta"\n',
        "scripts/ok.bat": '@echo off\ncd /d "%~dp0\\.."\n',
        "Dockerfile": "ARG BASE=python:3.13-slim\nFROM ${BASE}\nWORKDIR /app\n",
    }

    assert {
        path: standards.validate_source(PurePosixPath(path), content)
        for path, content in samples.items()
    } == {path: [] for path in samples}


def test_tracked_sources_include_untracked_files_and_exclude_deleted_files(
    tmp_path: Path,
) -> None:
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    tracked = tmp_path / "tracked.json"
    tracked.write_text("{}\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(tmp_path), "add", tracked.name), check=True)
    tracked.unlink()
    (tmp_path / "new.json").write_text("{}\n", encoding="utf-8")

    sources = standards._tracked_operational_sources(tmp_path)

    assert sources == [(PurePosixPath("new.json"), standards.SourceKind.JSON)]


def test_external_parsers_fail_closed_when_required_tools_are_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(standards, "_resolve_bash", lambda: None)
    monkeypatch.setattr(standards, "_resolve_powershell", lambda: None)
    sources = [
        (PurePosixPath("script.sh"), standards.SourceKind.SHELL),
        (PurePosixPath("script.ps1"), standards.SourceKind.POWERSHELL),
    ]

    violations = standards._run_external_syntax_checks(tmp_path, sources)

    assert {violation.message for violation in violations} == {
        "bash is required to parse tracked shell scripts",
        "PowerShell is required to parse tracked .ps1 scripts",
    }
