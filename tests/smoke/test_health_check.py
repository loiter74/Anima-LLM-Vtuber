from __future__ import annotations

from types import SimpleNamespace

import scripts.health_check as health_check
from scripts.health_check import _python_command, build_gates, redact_output


def test_requirements_entrypoint_includes_core_and_dev() -> None:
    requirements = (health_check.ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "-r requirements-core.txt" in requirements
    assert "-r requirements-dev.txt" in requirements


def test_requirement_files_are_ascii_for_windows_pip() -> None:
    for name in (
        "requirements.txt",
        "requirements-core.txt",
        "requirements-dev.txt",
        "requirements-local-ai.txt",
    ):
        data = (health_check.ROOT / name).read_bytes()
        data.decode("ascii")


def test_dev_requirements_include_socketio_websocket_transport() -> None:
    requirements = (health_check.ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    requirement_lines = [
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert any(line.startswith("websocket-client") for line in requirement_lines)


def test_build_gates_includes_required_health_domains() -> None:
    gate_ids = {gate.id for gate in build_gates()}

    assert {
        "backend:ruff",
        "backend:mypy",
        "backend:tests",
        "backend:coverage",
        "frontend:typecheck",
        "frontend:tests",
        "frontend:build",
        "frontend:coverage-script",
        "events:validate",
        "docker:compose-gpu-config",
        "docker:compose-cpu-config",
        "security:secrets",
        "dependencies:pip-check",
        "routes:smoke",
    }.issubset(gate_ids)


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


def test_python_command_skips_py_launcher_without_metrics_dependency(monkeypatch) -> None:
    monkeypatch.delenv("ANIMETTA_PYTHON", raising=False)
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
