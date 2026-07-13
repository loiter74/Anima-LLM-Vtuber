from __future__ import annotations

import json
from pathlib import Path

import pytest

from tooling.quality.cli import main

ROOT = Path(__file__).resolve().parents[3]


def _write_cli_fixture(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "pass.py"
    script.write_text("print('cli-pass')\n", encoding="utf-8")
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
groups:
  python-check:
    domain: repository
    kind: smoke
    runner: python
    entrypoint: pass.py
    timeout_seconds: 5
    include_in_full: true
  docs-check:
    domain: repository
    kind: contract
    runner: python
    entrypoint: pass.py
    timeout_seconds: 5
components:
  source:
    domain: repository
    paths: [src/**]
    direct_groups: [python-check]
  docs:
    domain: repository
    paths: [docs/**]
    direct_groups: [docs-check]
fallbacks:
  backend: [python-check]
  frontend: [python-check]
  repository: [python-check]
""".strip(),
        encoding="utf-8",
    )
    return manifest, script


def test_validate_and_explain_commands_emit_json(capsys) -> None:
    manifest = ROOT / "tooling" / "quality.yml"

    validate_code = main(["validate", "--manifest", str(manifest), "--json"])
    validate_payload = json.loads(capsys.readouterr().out)
    explain_code = main(
        [
            "explain",
            "src/animetta/orchestration/server/routes.py",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(ROOT),
            "--json",
        ]
    )
    explain_payload = json.loads(capsys.readouterr().out)

    assert validate_code == 0
    assert validate_payload["valid"] is True
    assert explain_code == 0
    assert "orchestration-server" in explain_payload["components"]
    assert "backend-server-unit" in explain_payload["groups"]


def test_plan_command_writes_frozen_plan_and_github_matrices(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    github_output = tmp_path / "github-output.txt"

    code = main(
        [
            "plan",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "quick",
            "--paths",
            "src/example.py",
            "--output",
            str(plan_path),
            "--github-output",
            str(github_output),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    outputs = github_output.read_text(encoding="utf-8")

    assert code == 0
    assert plan_path.exists()
    assert payload["groups"][0]["id"] == "python-check"
    assert 'python_groups=["python-check"]' in outputs
    assert "python " not in outputs


def test_run_command_executes_plan_and_writes_aggregate_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    results_dir = tmp_path / "results"
    assert (
        main(
            [
                "plan",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(tmp_path),
                "--tier",
                "quick",
                "--paths",
                "src/example.py",
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "run",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--results-dir",
            str(results_dir),
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert summary["status"] == "passed"
    assert (results_dir / "python-check.json").exists()
    assert (results_dir / "summary.json").exists()


def test_run_command_invalidates_stale_selected_evidence_before_execution(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    results_dir = tmp_path / "results"
    assert (
        main(
            [
                "plan",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(tmp_path),
                "--tier",
                "quick",
                "--paths",
                "src/example.py",
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    results_dir.mkdir()
    stale_result = results_dir / "python-check.json"
    stale_summary = results_dir / "summary.json"
    stale_result.write_text('{"status":"passed"}\n', encoding="utf-8")
    stale_summary.write_text('{"status":"passed"}\n', encoding="utf-8")

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("tooling.quality.cli.run_group", interrupt)

    with pytest.raises(KeyboardInterrupt):
        main(
            [
                "run",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(tmp_path),
                "--plan",
                str(plan_path),
                "--results-dir",
                str(results_dir),
            ]
        )

    assert not stale_result.exists()
    assert not stale_summary.exists()


def test_verify_command_plans_and_runs_in_one_invocation(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "evidence" / "plan.json"
    results_dir = tmp_path / "evidence" / "results"

    code = main(
        [
            "verify",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "quick",
            "--paths",
            "src/example.py",
            "--plan-output",
            str(plan_path),
            "--results-dir",
            str(results_dir),
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert summary["status"] == "passed"
    assert plan_path.exists()
    assert (results_dir / "python-check.json").exists()
    assert (results_dir / "summary.json").exists()


def test_verify_command_explains_frozen_groups_before_result(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)

    code = main(
        [
            "verify",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "quick",
            "--paths",
            "src/example.py",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert output.index("Plan ") < output.index("- python-check: direct match: source")
    assert output.index("- python-check: direct match: source") < output.index(
        "Quality result: passed"
    )


def test_worktree_discovery_failure_uses_repository_fallback(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"

    code = main(
        [
            "plan",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "affected",
            "--worktree",
            "--output",
            str(plan_path),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert [group["id"] for group in payload["groups"]] == ["python-check"]
    assert payload["fallbacks"]
    assert "discovery failure" in payload["fallbacks"][0]


def test_run_group_rejects_group_not_selected_by_plan(tmp_path: Path, capsys) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    assert (
        main(
            [
                "plan",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(tmp_path),
                "--tier",
                "quick",
                "--paths",
                "docs/readme.md",
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "run-group",
            "python-check",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--plan",
            str(plan_path),
        ]
    )

    assert code == 2
    assert "not selected" in capsys.readouterr().err


def test_run_rejects_tampered_frozen_plan(tmp_path: Path, capsys) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    assert (
        main(
            [
                "plan",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(tmp_path),
                "--tier",
                "quick",
                "--paths",
                "src/example.py",
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["groups"][0]["required"] = False
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    code = main(
        [
            "run",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--plan",
            str(plan_path),
        ]
    )

    assert code == 2
    assert "plan hash does not match plan contents" in capsys.readouterr().err


def test_aggregate_command_fails_for_missing_required_result(tmp_path: Path, capsys) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    plan_path = tmp_path / "plan.json"
    results_dir = tmp_path / "empty-results"
    results_dir.mkdir()
    assert (
        main(
            [
                "plan",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(tmp_path),
                "--tier",
                "quick",
                "--paths",
                "src/example.py",
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "aggregate",
            "--plan",
            str(plan_path),
            "--results-dir",
            str(results_dir),
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert code == 1
    assert summary["missing_groups"] == ["python-check"]


def test_makefile_exposes_stable_quality_entrypoints() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "quality-validate:" in makefile
    assert "test-quick:" in makefile
    assert "test-affected:" in makefile
    assert "test-full:" in makefile
    assert "tooling.quality verify --tier quick" in makefile
    assert "tooling.quality verify --tier affected" in makefile
    assert "tooling.quality verify --tier full" in makefile
    assert "local-quick" not in makefile
    assert "local-affected" not in makefile
    assert "local-full" not in makefile


def test_quality_workflow_is_documented_for_agents_and_maintainers() -> None:
    root_agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    test_agents = (ROOT / "tests" / "AGENTS.md").read_text(encoding="utf-8")
    project_health = (
        ROOT / "docs" / "development" / "project-health.md"
    ).read_text(encoding="utf-8")

    for text in (root_agents, test_agents, project_health):
        assert "test-quick" in text
        assert "test-affected" in text
        assert "test-full" in text
    assert "machine-selected" in root_agents
    assert "fresh Playwright capture" in project_health
    assert "plan_hash" in project_health
    assert "orthogonal" in project_health
    assert "docker-compose-contract" in root_agents
    assert "docker-compose-contract" in test_agents
