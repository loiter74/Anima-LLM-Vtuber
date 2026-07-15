from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from tooling.quality import cli as quality_cli
from tooling.quality.cli import _json_text, main
from tooling.quality.models import AggregateStatus, AggregateSummary

ROOT = Path(__file__).resolve().parents[3]


def test_machine_json_is_ascii_safe_for_windows_console_encodings() -> None:
    class Payload(BaseModel):
        output: str

    rendered = _json_text(Payload(output="✓ 构建完成"))

    rendered.encode("ascii")
    assert json.loads(rendered) == {"output": "✓ 构建完成"}


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
    cacheable: true
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


def test_verify_reuses_exact_local_cache_and_emits_current_result(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    cache_root = tmp_path / "cache"
    plan_one = tmp_path / "run-one" / "plan.json"
    results_one = tmp_path / "run-one" / "results"
    plan_two = tmp_path / "run-two" / "plan.json"
    results_two = tmp_path / "run-two" / "results"
    common = [
        "--manifest",
        str(manifest),
        "--repo-root",
        str(tmp_path),
        "--tier",
        "quick",
        "--paths",
        "src/example.py",
        "--cache",
        "read-write",
        "--trust-scope",
        "local",
        "--cache-root",
        str(cache_root),
        "--json",
    ]

    assert (
        main(["verify", *common, "--plan-output", str(plan_one), "--results-dir", str(results_one)])
        == 0
    )
    first_summary = json.loads(capsys.readouterr().out)
    assert first_summary["cache_hit_groups"] == []

    assert (
        main(["verify", *common, "--plan-output", str(plan_two), "--results-dir", str(results_two)])
        == 0
    )
    second_summary = json.loads(capsys.readouterr().out)
    second_result = json.loads((results_two / "python-check.json").read_text(encoding="utf-8"))

    assert second_summary["cache_hit_groups"] == ["python-check"]
    assert second_summary["cache_hit_ratio"] == 1
    assert second_result["execution_mode"] == "cache-hit"
    assert (
        second_result["plan_hash"] == json.loads(plan_two.read_text(encoding="utf-8"))["plan_hash"]
    )


def test_full_tier_defaults_to_cold_cache_off(tmp_path: Path, capsys) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    results_dir = tmp_path / "results"

    code = main(
        [
            "verify",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "full",
            "--paths",
            "src/example.py",
            "--results-dir",
            str(results_dir),
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    result = json.loads((results_dir / "python-check.json").read_text(encoding="utf-8"))

    assert code == 0
    assert summary["cache_hit_groups"] == []
    assert result["execution_mode"] == "executed"
    assert result["cache_reason"] == "cache-off"


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


def test_docker_build_command_executes_only_frozen_selected_service(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    manifest = ROOT / "tooling" / "quality.yml"
    plan_path = tmp_path / "plan.json"
    assert (
        main(
            [
                "plan",
                "--manifest",
                str(manifest),
                "--repo-root",
                str(ROOT),
                "--tier",
                "affected",
                "--paths",
                "src/animetta_qwen_tts/app.py",
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    calls: list[tuple[list[str], dict[str, str]]] = []
    decoder_options: list[tuple[object, object]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs["env"]))  # type: ignore[arg-type]
        decoder_options.append((kwargs.get("encoding"), kwargs.get("errors")))
        return subprocess.CompletedProcess(argv, 0, stdout="built", stderr="")

    monkeypatch.setattr("tooling.quality.cli.subprocess.run", run)
    code = main(
        [
            "docker-build",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(ROOT),
            "--plan",
            str(plan_path),
            "--no-cache",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert calls[0][0][-3:] == ["build", "--no-cache", "qwen-tts"]
    assert "animetta" not in calls[0][0]
    assert calls[0][1]["QWEN_TTS_BUILD_FINGERPRINT"] == payload["actions"][0]["input_fingerprint"]
    assert decoder_options == [("utf-8", "replace")]


def test_benchmark_command_primes_then_records_warm_latency_and_hits(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    output = tmp_path / "benchmark.json"

    code = main(
        [
            "benchmark",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "quick",
            "--paths",
            "src/example.py",
            "--iterations",
            "2",
            "--output",
            str(output),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert output.exists()
    assert payload["warm_run_count"] == 2
    assert len(payload["warm_runs"]) == 2
    assert payload["cache_hit_ratio"] == 1
    assert payload["planning_seconds"] <= 5
    assert payload["warm_p95_seconds"] >= 0


def test_benchmark_stops_before_warm_runs_when_priming_fails(
    tmp_path: Path,
    capsys,
) -> None:
    manifest, script = _write_cli_fixture(tmp_path)
    script.write_text("raise SystemExit(1)\n", encoding="utf-8")
    output = tmp_path / "benchmark.json"

    code = main(
        [
            "benchmark",
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--tier",
            "quick",
            "--paths",
            "src/example.py",
            "--iterations",
            "2",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    benchmark_roots = list(tmp_path.glob("benchmark-*"))

    assert code == 1
    assert "priming failed" in captured.err.lower()
    assert output.exists() is False
    assert len(benchmark_roots) == 1
    assert (benchmark_roots[0] / "prime" / "summary.json").exists()
    assert list(benchmark_roots[0].glob("warm-*")) == []


def test_failed_benchmark_rerun_removes_prior_success_evidence(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _ = _write_cli_fixture(tmp_path)
    output = tmp_path / "benchmark.json"
    argv = [
        "benchmark",
        "--manifest",
        str(manifest),
        "--repo-root",
        str(tmp_path),
        "--tier",
        "quick",
        "--paths",
        "src/example.py",
        "--iterations",
        "1",
        "--output",
        str(output),
    ]

    assert main(argv) == 0
    capsys.readouterr()
    benchmark_root = next(tmp_path.glob("benchmark-*"))
    prior_summary = AggregateSummary.model_validate_json(
        (benchmark_root / "prime" / "summary.json").read_text(encoding="utf-8")
    )
    failed_summary = prior_summary.model_copy(update={"status": AggregateStatus.FAILED})

    monkeypatch.setattr(
        quality_cli,
        "_execute_plan",
        lambda *_args, **_kwargs: (AggregateStatus.FAILED, failed_summary),
    )

    assert main(argv) == 1
    capsys.readouterr()
    assert output.exists() is False
    assert list(benchmark_root.glob("warm-*")) == []


def test_makefile_exposes_stable_quality_entrypoints() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "quality-validate:" in makefile
    assert "format-check:" in makefile
    assert "frontend-lint:" in makefile
    assert "frontend-format-check:" in makefile
    assert "ruff check src/ tooling/ scripts/ evaluations/ tests/" in makefile
    assert "ruff format --check src/ tooling/ scripts/ evaluations/ tests/" in makefile
    assert "pnpm --dir frontend lint" in makefile
    assert "pnpm --dir frontend format:check" in makefile
    assert "test-quick:" in makefile
    assert "test-affected:" in makefile
    assert "test-full:" in makefile
    assert "tooling.quality verify --tier quick" in makefile
    assert "tooling.quality verify --tier affected" in makefile
    assert "tooling.quality verify --tier full" in makefile
    assert "verify --tier quick --worktree --cache read-write" in makefile
    assert "verify --tier affected --worktree --cache read-write" in makefile
    assert "verify --tier full --worktree --cache off" in makefile
    assert "plan --tier full --worktree --output" in makefile
    assert "scripts/release_runtime_gate.py --plan $(QUALITY_DOCKER_FULL_PLAN)" in makefile
    assert "benchmark --tier quick" in makefile
    assert "docker-build --plan" in makefile
    assert "local-quick" not in makefile
    assert "local-affected" not in makefile
    assert "local-full" not in makefile


def test_quality_workflow_is_documented_for_agents_and_maintainers() -> None:
    root_agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    test_agents = (ROOT / "tests" / "AGENTS.md").read_text(encoding="utf-8")
    project_health = (ROOT / "docs" / "development" / "project-health.md").read_text(
        encoding="utf-8"
    )

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
    assert "content fingerprint" in project_health
    assert "trust-scoped" in project_health
    assert "weighted DAG" in project_health
    assert "warm topology" in project_health
    assert "P95" in project_health
    assert "test-affected-shadow" in test_agents
    assert "benchmark-quick" in test_agents
    assert "cache off" in root_agents
