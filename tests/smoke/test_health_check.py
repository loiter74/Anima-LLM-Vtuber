from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.health_check as health_check
from scripts.health_check import _python_command, build_gates, redact_output


@pytest.fixture(autouse=True)
def _clear_python_dependency_probe_cache() -> Iterator[None]:
    health_check._python_has_health_dependencies.cache_clear()
    yield
    health_check._python_has_health_dependencies.cache_clear()


def test_requirements_entrypoints_have_one_way_dependency_layers() -> None:
    runtime = (health_check.ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev = (health_check.ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    local_ai = (health_check.ROOT / "requirements-local-ai.txt").read_text(encoding="utf-8")
    runtime_entries = [
        line.strip()
        for line in runtime.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "starlette" in runtime
    assert not any(line.startswith("-r ") for line in runtime_entries)
    assert "-r requirements.txt" in dev
    assert "-r requirements.txt" in local_ai


def test_requirement_files_are_ascii_for_windows_pip() -> None:
    for name in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-local-ai.txt",
    ):
        data = (health_check.ROOT / name).read_bytes()
        data.decode("ascii")


def test_runtime_and_dev_requirements_include_required_transports() -> None:
    runtime = (health_check.ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev = (health_check.ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    runtime_lines = [
        line.strip()
        for line in runtime.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    dev_lines = [
        line.strip()
        for line in dev.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert any(line.startswith("bilibili-api-python") for line in runtime_lines)
    assert any(line.startswith("websocket-client") for line in dev_lines)
    assert any(line.startswith("pytest-cov") for line in dev_lines)


def test_build_gates_includes_required_health_domains() -> None:
    gate_ids = {gate.id for gate in build_gates("full")}

    assert {
        "quality:full",
        "frontend:coverage-script",
        "frontend:font-policy",
        "docs:backend-framework",
        "dependencies:pip-check",
        "dependencies:frontend-audit",
    }.issubset(gate_ids)
    assert "security:secrets" not in gate_ids


def test_build_gates_exposes_quick_affected_full_and_docker_profiles() -> None:
    quick_ids = {gate.id for gate in build_gates("quick")}
    affected_ids = {gate.id for gate in build_gates("affected")}
    full_ids = {gate.id for gate in build_gates("full")}
    docker_ids = {gate.id for gate in build_gates("docker")}

    assert "backend:ruff" in quick_ids
    assert "quality:affected" not in quick_ids
    assert affected_ids == {"quality:affected"}
    assert "quality:full" in full_ids
    assert {
        "backend:tests",
        "backend:coverage",
        "frontend:typecheck",
        "frontend:tests",
        "frontend:build",
    }.isdisjoint(full_ids)
    assert {
        "docker:compose-config",
        "docker:health-endpoint",
        "docker:frontend-endpoint",
        "docker:logs-clean",
    }.issubset(docker_ids)


def test_quality_health_gates_use_single_plan_and_run_command() -> None:
    affected = next(gate for gate in build_gates("affected") if gate.id == "quality:affected")
    full = next(gate for gate in build_gates("full") if gate.id == "quality:full")

    assert "verify" in affected.command
    assert affected.command.count("affected") == 1
    assert "--results-dir" not in affected.command
    assert "verify" in full.command
    assert full.command.count("full") == 1
    assert "--results-dir" not in full.command


def test_redact_output_masks_secret_like_values() -> None:
    raw = (
        "MIMO_API_KEY=sk-live-secret\n"
        "DEEPSEEK_API_KEY: sk-compose-secret\n"
        "Authorization: Bearer abc.def.ghi\n"
        "safe line"
    )

    redacted = redact_output(raw)

    assert "sk-live-secret" not in redacted
    assert "sk-compose-secret" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "MIMO_API_KEY=<redacted>" in redacted
    assert "DEEPSEEK_API_KEY: <redacted>" in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "safe line" in redacted


def test_python_command_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ANIMETTA_PYTHON", "py -3.13")

    assert _python_command() == ("py", "-3.13")


def test_python_command_skips_unusable_repo_venv(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANIMETTA_PYTHON", raising=False)
    monkeypatch.setattr(health_check, "ROOT", tmp_path)
    monkeypatch.setattr(health_check.os, "name", "nt")
    monkeypatch.setattr(health_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(health_check.sys, "executable", "current-python")

    repo_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    repo_python.parent.mkdir(parents=True)
    repo_python.touch()

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0 if command[0] == "current-python" else 1)

    monkeypatch.setattr(health_check.subprocess, "run", fake_run)

    assert _python_command() == ("current-python",)


def test_python_command_skips_py_launcher_without_metrics_dependency(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ANIMETTA_PYTHON", raising=False)
    monkeypatch.setattr(health_check, "ROOT", tmp_path)
    monkeypatch.setattr(health_check.os, "name", "nt")
    monkeypatch.setattr(health_check.shutil, "which", lambda name: "py.exe")
    monkeypatch.setattr(health_check.sys, "executable", "current-python")

    def fake_run(command, **kwargs):
        probe = command[-1]
        if command[0] == "py" and "prometheus_client" not in probe:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0 if command[0] == "current-python" else 1)

    monkeypatch.setattr(health_check.subprocess, "run", fake_run)

    assert _python_command() == ("current-python",)


def test_pnpm_command_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ANIMETTA_PNPM", "corepack pnpm")

    assert health_check._pnpm_command() == ("corepack", "pnpm")


def test_pnpm_command_prefers_windows_pnpm_cmd(monkeypatch) -> None:
    monkeypatch.delenv("ANIMETTA_PNPM", raising=False)
    monkeypatch.setattr(health_check.os, "name", "nt")

    def fake_which(name: str) -> str | None:
        return "C:/node/pnpm.cmd" if name == "pnpm.cmd" else None

    monkeypatch.setattr(health_check.shutil, "which", fake_which)

    assert health_check._pnpm_command() == ("C:/node/pnpm.cmd",)


def test_pnpm_command_falls_back_to_corepack(monkeypatch) -> None:
    monkeypatch.delenv("ANIMETTA_PNPM", raising=False)
    monkeypatch.setattr(health_check.os, "name", "nt")

    def fake_which(name: str) -> str | None:
        return "C:/node/corepack.cmd" if name == "corepack.cmd" else None

    monkeypatch.setattr(health_check.shutil, "which", fake_which)

    assert health_check._pnpm_command() == ("C:/node/corepack.cmd", "pnpm")


@pytest.mark.parametrize("minor", [11, 12, 14])
def test_python_runtime_preflight_rejects_noncanonical_python(minor, monkeypatch) -> None:
    monkeypatch.setattr(health_check, "_python_command", lambda: ("python",))

    def fake_probe(command, code):
        return {"major": 3, "minor": minor, "micro": 11, "executable": "python"}

    monkeypatch.setattr(health_check, "_run_json_python_probe", fake_probe)

    check = health_check.check_python_runtime()

    assert check.status == health_check.HEALTH_FAIL
    assert check.warning is None
    assert "Python 3.13" in check.remediation


def test_pytest_plugin_preflight_reports_missing_plugins(monkeypatch) -> None:
    monkeypatch.setattr(health_check, "_python_command", lambda: ("python",))

    def fake_probe(command, code):
        return {"missing": ["pytest-xdist", "pytest-timeout"]}

    monkeypatch.setattr(health_check, "_run_json_python_probe", fake_probe)

    check = health_check.check_pytest_plugins()

    assert check.status == health_check.HEALTH_FAIL
    assert "pytest-xdist" in check.message
    assert "requirements-dev.txt" in check.remediation


def test_frontend_audit_registry_failure_is_degraded() -> None:
    gate = next(
        gate for gate in build_gates(profile=None) if gate.id == "dependencies:frontend-audit"
    )

    status, remediation, warnings = health_check._classify_gate(
        gate,
        1,
        "ERR_PNPM_AUDIT FetchError: request to registry.npmjs.org advisories fetch failed",
    )

    assert status == health_check.HEALTH_DEGRADED
    assert "registry" in remediation.lower()
    assert warnings[0]["id"] == "dependencies:frontend-audit-registry"


def test_frontend_audit_gate_uses_python_validator() -> None:
    gate = next(
        gate for gate in build_gates(profile=None) if gate.id == "dependencies:frontend-audit"
    )

    assert "_frontend_audit_validation" in " ".join(gate.command)


def test_collect_pnpm_lock_versions(tmp_path: Path) -> None:
    lockfile = tmp_path / "pnpm-lock.yaml"
    lockfile.write_text(
        """
lockfileVersion: '9.0'
packages:
  vue@3.5.0: {}
  '@scope/pkg@1.2.3(peer@4.5.6)': {}
""",
        encoding="utf-8",
    )

    versions = health_check._collect_pnpm_lock_versions(lockfile)

    assert versions["vue"] == ["3.5.0"]
    assert versions["@scope/pkg"] == ["1.2.3"]


def test_frontend_audit_uses_bulk_fallback_after_pnpm_fetch_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text(
        """
lockfileVersion: '9.0'
packages:
  vue@3.5.0: {}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(health_check, "FRONTEND", tmp_path)
    monkeypatch.setattr(health_check, "_pnpm_command", lambda: ("pnpm",))

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout='{"error":{"message":"fetch failed"}}')

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setattr(health_check.subprocess, "run", fake_run)
    monkeypatch.setattr(
        health_check.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse()
    )

    health_check._frontend_audit_validation()

    assert "bulk advisory fallback" in capsys.readouterr().out


def test_summary_contains_contract_fields(tmp_path: Path) -> None:
    gate = build_gates("quick")[0]
    result = health_check.GateResult(
        gate=gate,
        returncode=0,
        output="",
        duration_s=0.1,
        status=health_check.HEALTH_PASS,
        remediation="",
    )

    summary = health_check.build_summary(
        "quick",
        [health_check.PreflightCheck("python:runtime", health_check.HEALTH_PASS, "ok")],
        [result],
    )
    output = tmp_path / "health.json"
    health_check.write_summary(output, summary)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["python_policy"] == {"canonical": "3.13"}
    assert all(
        warning["id"] != "python:runtime-degraded" for warning in saved["accepted_warning_ledger"]
    )
    assert "health_statuses" in saved
    assert "gates" in saved
