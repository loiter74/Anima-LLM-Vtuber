from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from tooling.quality.aggregate import aggregate_results
from tooling.quality.executor import build_argv, detect_capabilities, run_group, write_result
from tooling.quality.manifest import load_catalog
from tooling.quality.models import (
    AggregateStatus,
    AggregateSummary,
    Capability,
    PlannedGroup,
    ResultStatus,
    Runner,
    Tier,
    VerificationPlan,
    VerificationResult,
)

ROOT = Path(__file__).resolve().parents[3]


def test_detect_capabilities_accepts_explicit_live_environment_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANIMETTA_QUALITY_CAPABILITIES", "network, gpu")

    detected = detect_capabilities(ROOT)

    assert {Capability.NETWORK, Capability.GPU}.issubset(detected)


def test_detect_capabilities_rejects_unknown_or_machine_detected_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANIMETTA_QUALITY_CAPABILITIES", "network,docker,unknown")

    with pytest.raises(ValueError, match="ANIMETTA_QUALITY_CAPABILITIES"):
        detect_capabilities(ROOT)


def _repository_catalog():
    return load_catalog(ROOT / "tooling" / "quality.yml")


def _plan_with_group(group_id: str) -> VerificationPlan:
    loaded = _repository_catalog()
    group = loaded.catalog.groups[group_id]
    planned = PlannedGroup(
        id=group_id,
        domain=group.domain,
        kind=group.kind,
        runner=group.runner,
        isolation=group.isolation,
        capabilities=group.capabilities,
        depends_on=group.depends_on,
        artifacts=group.artifacts,
        required=group.required,
        reasons=("test",),
    )
    return VerificationPlan(
        tier=Tier.QUICK,
        source="paths",
        changes=(),
        groups=(planned,),
        required_capabilities=frozenset(group.capabilities),
        manifest_hash=loaded.manifest_hash,
        plan_hash="a" * 64,
    )


def _write_python_catalog(tmp_path: Path, script_name: str, timeout: int) -> Path:
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        f"""
schema_version: 1
groups:
  python-check:
    domain: repository
    kind: smoke
    runner: python
    entrypoint: {script_name}
    timeout_seconds: {timeout}
components:
  tooling:
    domain: repository
    paths: [tooling/**]
    direct_groups: [python-check]
fallbacks:
  backend: [python-check]
  frontend: [python-check]
  repository: [python-check]
""".strip(),
        encoding="utf-8",
    )
    return manifest


def test_build_argv_uses_fixed_pytest_runner_without_shell() -> None:
    loaded = _repository_catalog()

    argv = build_argv(
        loaded.catalog.groups["backend-core-unit"],
        python_executable=sys.executable,
        pnpm_executable="pnpm",
        docker_executable="docker",
    )

    assert argv[:4] == [sys.executable, "-m", "pytest", "tests/core"]
    assert "-m" in argv
    assert not any(part == "pytest tests/core" for part in argv)


def test_python_tool_runners_use_the_canonical_interpreter() -> None:
    loaded = _repository_catalog()

    ruff_argv = build_argv(
        loaded.catalog.groups["backend-static"],
        python_executable=sys.executable,
    )
    mypy_argv = build_argv(
        loaded.catalog.groups["backend-typecheck"],
        python_executable=sys.executable,
    )

    assert ruff_argv[:3] == [sys.executable, "-m", "ruff"]
    assert mypy_argv[:3] == [sys.executable, "-m", "mypy"]


def test_code_standard_groups_use_canonical_local_commands() -> None:
    loaded = _repository_catalog()

    format_argv = build_argv(
        loaded.catalog.groups["python-format"],
        python_executable=sys.executable,
    )
    frontend_lint_argv = build_argv(
        loaded.catalog.groups["frontend-lint"],
        pnpm_executable="pnpm",
    )
    frontend_format_argv = build_argv(
        loaded.catalog.groups["frontend-format"],
        pnpm_executable="pnpm",
    )
    operational_argv = build_argv(
        loaded.catalog.groups["operational-source-contract"],
        python_executable=sys.executable,
    )
    deadcode_argv = build_argv(
        loaded.catalog.groups["backend-deadcode"],
        python_executable=sys.executable,
    )

    assert format_argv == [
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--check",
        "src",
        "tooling",
        "scripts",
        "evaluations",
        "tests",
    ]
    assert frontend_lint_argv == ["pnpm", "lint"]
    assert frontend_format_argv == ["pnpm", "format:check"]
    assert operational_argv == [
        sys.executable,
        "scripts/check_source_standards.py",
        "--check",
    ]
    assert deadcode_argv == [
        sys.executable,
        "-m",
        "vulture",
        "tooling",
        "scripts",
        "evaluations",
        "src/animetta",
        "src/animetta_qwen_tts",
        "--min-confidence",
        "80",
    ]


def test_required_frontend_lint_fails_closed_when_pnpm_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _repository_catalog()

    monkeypatch.setattr("tooling.quality.executor.shutil.which", lambda _: None)

    def missing_pnpm(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("pnpm is unavailable")

    monkeypatch.setattr("tooling.quality.executor.subprocess.Popen", missing_pnpm)
    result = run_group(
        loaded,
        "frontend-lint",
        plan_hash="a" * 64,
        repo_root=ROOT,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.FAILED
    assert result.failure_kind == "launch"
    assert "pnpm is unavailable" in result.remediation


def test_build_argv_uses_catalogued_playwright_smoke_entrypoint() -> None:
    loaded = _repository_catalog()
    group = loaded.catalog.groups["frontend-playwright-smoke"]

    argv = build_argv(group, pnpm_executable="pnpm")

    assert group.runner is Runner.PLAYWRIGHT
    assert argv == ["pnpm", "exec", "node", "smoke-test.mjs"]


def test_docker_contract_validates_quietly_without_serializing_compose_secrets() -> None:
    loaded = _repository_catalog()

    argv = build_argv(loaded.catalog.groups["docker-compose-contract"])

    assert argv[-2:] == ["config", "--quiet"]
    assert "--format" not in argv


def test_run_group_blocks_when_required_capability_is_missing() -> None:
    loaded = _repository_catalog()

    result = run_group(
        loaded,
        "docker-compose-contract",
        plan_hash="a" * 64,
        repo_root=ROOT,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.BLOCKED
    assert result.failure_kind == "capability"
    assert "docker" in result.remediation


def test_docker_contract_validates_quietly_without_rendering_environment() -> None:
    loaded = _repository_catalog()

    argv = build_argv(
        loaded.catalog.groups["docker-compose-contract"],
        docker_executable="docker",
    )

    assert argv == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "config",
        "--quiet",
    ]


def test_run_group_executes_real_python_process_and_writes_result(tmp_path: Path) -> None:
    script = tmp_path / "pass.py"
    script.write_text("print('quality-pass')\n", encoding="utf-8")
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=5))

    result = run_group(
        loaded,
        "python-check",
        plan_hash="b" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )
    output = tmp_path / "result.json"
    write_result(result, output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert result.status is ResultStatus.PASSED
    assert result.exit_code == 0
    assert "quality-pass" in result.output
    assert payload["plan_hash"] == "b" * 64
    assert payload["status"] == "passed"


def test_run_group_can_override_arguments_for_a_feedback_shard(tmp_path: Path) -> None:
    script = tmp_path / "args.py"
    script.write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=5))

    result = run_group(
        loaded,
        "python-check",
        plan_hash="b" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
        args_override=("feedback", "shard"),
    )

    assert result.status is ResultStatus.PASSED
    assert "feedback|shard" in result.output


def test_run_group_preserves_escaped_pytest_node_ids(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_unicode.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', ['晚'])\n"
        "def test_unicode(value):\n"
        "    assert value == '晚'\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
groups:
  unicode-tests:
    domain: repository
    kind: unit
    runner: pytest
    targets: [tests/test_unicode.py]
    args: [-q, -o, addopts=]
    timeout_seconds: 5
components:
  source:
    domain: repository
    paths: [tests/**]
    direct_groups: [unicode-tests]
fallbacks:
  backend: [unicode-tests]
  frontend: [unicode-tests]
  repository: [unicode-tests]
""".strip(),
        encoding="utf-8",
    )
    loaded = load_catalog(manifest)

    result = run_group(
        loaded,
        "unicode-tests",
        plan_hash="b" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
        targets_override=(r"tests/test_unicode.py::test_unicode[\u665a]",),
    )

    assert result.status is ResultStatus.PASSED


def test_run_group_records_declared_artifacts_in_structured_result(
    tmp_path: Path,
) -> None:
    script = tmp_path / "report.py"
    script.write_text(
        "from pathlib import Path\nPath('report.json').write_text('{}')\n",
        encoding="utf-8",
    )
    manifest = _write_python_catalog(tmp_path, script.name, timeout=5)
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "timeout_seconds: 5",
            "timeout_seconds: 5\n    artifacts: [report.json]",
            1,
        ),
        encoding="utf-8",
    )
    loaded = load_catalog(manifest)

    result = run_group(
        loaded,
        "python-check",
        plan_hash="f" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.PASSED
    assert result.artifacts == ("report.json",)


def test_run_group_redacts_secret_values_from_persistent_output(tmp_path: Path) -> None:
    script = tmp_path / "secret.py"
    script.write_text("print('DEEPSEEK_API_KEY=do-not-persist')\n", encoding="utf-8")
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=5))

    result = run_group(
        loaded,
        "python-check",
        plan_hash="d" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.PASSED
    assert "do-not-persist" not in result.output
    assert "DEEPSEEK_API_KEY=<redacted>" in result.output


def test_run_group_redacts_secret_environment_values_from_output(
    tmp_path: Path, monkeypatch
) -> None:
    script = tmp_path / "print_secret.py"
    script.write_text(
        "import os\nprint(os.environ['QUALITY_TEST_API_KEY'])\n",
        encoding="utf-8",
    )
    secret = "live-" + ("r" * 40)
    monkeypatch.setenv("QUALITY_TEST_API_KEY", secret)
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=5))

    result = run_group(
        loaded,
        "python-check",
        plan_hash="d" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.PASSED
    assert secret not in result.output
    assert "<redacted:QUALITY_TEST_API_KEY>" in result.output


def test_run_group_redacts_sensitive_values_loaded_indirectly_from_dotenv(
    tmp_path: Path,
) -> None:
    secret = "compose-" + ("s" * 40)
    (tmp_path / ".env").write_text(f"COMPOSE_TEST_SECRET={secret}\n", encoding="utf-8")
    script = tmp_path / "read_dotenv.py"
    script.write_text(
        "from pathlib import Path\nprint(Path('.env').read_text().split('=', 1)[1])\n",
        encoding="utf-8",
    )
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=5))

    result = run_group(
        loaded,
        "python-check",
        plan_hash="e" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.PASSED
    assert secret not in result.output
    assert "<redacted:COMPOSE_TEST_SECRET>" in result.output


def test_run_group_reports_timeout_from_real_process(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "slow.py"
    script.write_text(
        "import os, time\nprint(os.environ['QUALITY_TEST_TOKEN'], flush=True)\ntime.sleep(5)\n",
        encoding="utf-8",
    )
    secret = "live-" + ("t" * 40)
    monkeypatch.setenv("QUALITY_TEST_TOKEN", secret)
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=1))

    result = run_group(
        loaded,
        "python-check",
        plan_hash="c" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.FAILED
    assert result.failure_kind == "timeout"
    assert result.exit_code is None
    assert secret not in result.output
    assert "<redacted:QUALITY_TEST_TOKEN>" in result.output


def test_run_group_reports_progress_while_process_is_active(tmp_path: Path) -> None:
    script = tmp_path / "progress.py"
    script.write_text("import time\ntime.sleep(0.35)\n", encoding="utf-8")
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=5))
    heartbeats: list[float] = []

    result = run_group(
        loaded,
        "python-check",
        plan_hash="c" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
        progress_callback=heartbeats.append,
        progress_interval_seconds=0.1,
    )

    assert result.status is ResultStatus.PASSED
    assert len(heartbeats) >= 2
    assert heartbeats == sorted(heartbeats)


def test_run_group_cancels_real_child_process_promptly(tmp_path: Path) -> None:
    script = tmp_path / "cancel.py"
    script.write_text(
        "import os, time\n"
        "from pathlib import Path\n"
        "Path('pid.txt').write_text(str(os.getpid()))\n"
        "print('started', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    loaded = load_catalog(_write_python_catalog(tmp_path, script.name, timeout=60))
    cancellation = threading.Event()
    timer = threading.Timer(0.2, cancellation.set)
    timer.start()
    started = time.perf_counter()
    try:
        result = run_group(
            loaded,
            "python-check",
            plan_hash="c" * 64,
            repo_root=tmp_path,
            available_capabilities=frozenset(),
            cancellation_event=cancellation,
        )
    finally:
        timer.cancel()

    assert time.perf_counter() - started < 3
    assert result.status is ResultStatus.CANCELLED
    assert result.failure_kind == "cancelled"
    assert "started" in result.output


def test_run_group_reports_process_launch_error_as_structured_result(
    tmp_path: Path,
) -> None:
    script = tmp_path / "pass.py"
    script.write_text("print('never-started')\n", encoding="utf-8")
    manifest = _write_python_catalog(tmp_path, script.name, timeout=5)
    text = manifest.read_text(encoding="utf-8").replace(
        "entrypoint: pass.py",
        "entrypoint: pass.py\n    cwd: missing-directory",
    )
    manifest.write_text(text, encoding="utf-8")
    loaded = load_catalog(manifest)

    result = run_group(
        loaded,
        "python-check",
        plan_hash="e" * 64,
        repo_root=tmp_path,
        available_capabilities=frozenset(),
    )

    assert result.status is ResultStatus.FAILED
    assert result.failure_kind == "launch"
    assert result.exit_code is None
    assert "missing-directory" in result.remediation


def test_aggregate_fails_when_required_result_is_missing() -> None:
    plan = _plan_with_group("backend-core-unit")

    summary = aggregate_results(plan, [])

    assert summary.status is AggregateStatus.FAILED
    assert summary.missing_groups == ("backend-core-unit",)


def test_aggregate_fails_when_required_group_is_skipped() -> None:
    plan = _plan_with_group("backend-core-unit")
    result = VerificationResult(
        group_id="backend-core-unit",
        required=True,
        status=ResultStatus.SKIPPED,
        exit_code=None,
        duration_seconds=0,
        failure_kind="capability",
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
    )

    summary = aggregate_results(plan, [result])

    assert summary.status is AggregateStatus.FAILED
    assert summary.blocked_groups == ("backend-core-unit",)


def test_aggregate_allows_failed_optional_group_as_degraded() -> None:
    plan = _plan_with_group("frontend-playwright-smoke")
    result = VerificationResult(
        group_id="frontend-playwright-smoke",
        required=False,
        status=ResultStatus.FAILED,
        exit_code=1,
        duration_seconds=0.1,
        failure_kind="process",
        artifacts=(),
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
        output="failed",
    )

    summary = aggregate_results(plan, [result])

    assert summary.status is AggregateStatus.DEGRADED
    assert summary.failed_groups == ("frontend-playwright-smoke",)


def test_aggregate_records_missing_optional_group_as_degraded() -> None:
    plan = _plan_with_group("frontend-playwright-smoke")

    summary = aggregate_results(plan, [])

    assert summary.status is AggregateStatus.DEGRADED
    assert summary.missing_groups == ("frontend-playwright-smoke",)


def test_plan_result_and_summary_require_current_evidence_schema() -> None:
    plan = _plan_with_group("backend-core-unit")
    result = VerificationResult(
        group_id="backend-core-unit",
        required=True,
        status=ResultStatus.PASSED,
        exit_code=0,
        duration_seconds=0.1,
        plan_hash=plan.plan_hash,
        manifest_hash=plan.manifest_hash,
    )
    summary = aggregate_results(plan, [result])

    assert plan.schema_version == 3
    assert result.schema_version == 2
    assert summary.schema_version == 2

    for model, payload in (
        (VerificationPlan, plan.model_dump(mode="json")),
        (VerificationResult, result.model_dump(mode="json")),
        (AggregateSummary, summary.model_dump(mode="json")),
    ):
        payload["schema_version"] = 1
        with pytest.raises(ValidationError, match="schema_version"):
            model.model_validate(payload)
