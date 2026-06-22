from __future__ import annotations

from scripts.health_check import _python_command, build_gates, redact_output


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
