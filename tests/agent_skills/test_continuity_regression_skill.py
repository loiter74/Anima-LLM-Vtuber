"""Contracts for the repository conversation-continuity regression Skill."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from animetta.acceptance.conversation_continuity import (
    EXPECTATIONS,
    ContinuityStepEvidence,
    build_sanitized_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/skills/verify-conversation-continuity/scripts/run_regression.py"
SKILL = ROOT / ".agents/skills/verify-conversation-continuity"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("continuity_skill_regression", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "groups": [{"id": "livestream-continuity-contract"}],
        "fallbacks": [],
        "unmapped_paths": [],
        "docker_actions": [],
    }
    payload.update(changes)
    return payload


def _valid_evidence() -> dict[str, object]:
    steps = [
        ContinuityStepEvidence(
            step_id=step_id,
            trace_id=f"trace-{index}",
            scope_kind=expectation.scope_kind,
            window_before=expectation.window_before,
            window_after=expectation.window_after,
            committed=expectation.committed,
            actor_role=expectation.actor_role,
            source=expectation.source,
            public_fact_recalled=(True if index >= 2 else None),
            private_marker_absent=(True if index >= 2 else None),
        )
        for index, (step_id, expectation) in enumerate(EXPECTATIONS.items())
    ]
    return build_sanitized_evidence(
        run_id="skill-test",
        provider_real=True,
        socket_recreated=True,
        steps=steps,
    )


def _fake_runner(
    calls: list[tuple[str, ...]],
    *,
    plan: dict[str, object] | None = None,
    evidence: dict[str, object] | None = None,
    fail_on: str | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(
        argv: Sequence[str],
        *,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        del timeout_seconds
        command = tuple(argv)
        calls.append(command)
        if fail_on and fail_on in command:
            return subprocess.CompletedProcess(command, 1, "", "failed")
        if "plan" in command:
            output = Path(command[command.index("--output") + 1])
            output.write_text(json.dumps(plan or _plan_payload()), encoding="utf-8")
        if "scripts/conversation_continuity_canary.py" in command:
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence or _valid_evidence()), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_default_mode_runs_only_the_focused_quality_group(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "_run_command", _fake_runner(calls))

    exit_code = module.main([])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["mode"] == "deterministic"
    assert summary["status"] == "passed"
    assert summary["evidence_path"] is None
    assert len(calls) == 2
    assert calls[0][3:6] == ("plan", "--tier", "affected")
    assert module.PLAN_ANCHOR in calls[0]
    assert calls[1][3:5] == ("run-group", module.GROUP_ID)
    assert all("conversation_continuity_canary.py" not in call for call in calls)
    assert all("docker" not in call for call in calls)


@pytest.mark.parametrize(
    ("changes", "error_code"),
    [
        ({"groups": []}, "continuity_group_missing"),
        (
            {"groups": [{"id": "livestream-continuity-contract"}, {"id": "backend-full"}]},
            "backend_full_selected",
        ),
        ({"fallbacks": ["backend-full"]}, "quality_fallback_selected"),
        ({"unmapped_paths": ["unknown.py"]}, "quality_path_unmapped"),
        ({"docker_actions": [{"scope_id": "animetta"}]}, "docker_action_selected"),
    ],
)
def test_deterministic_mode_rejects_unsafe_quality_plans(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changes: dict[str, object],
    error_code: str,
) -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    plan = _plan_payload(**changes)
    monkeypatch.setattr(module, "_run_command", _fake_runner(calls, plan=plan))

    exit_code = module.main([])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert summary["error_codes"] == [error_code]
    assert len(calls) == 1


def test_runtime_mode_runs_deterministic_then_canary_and_validates_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(module, "_run_command", _fake_runner(calls))

    exit_code = module.main(
        ["--mode", "runtime", "--url", "http://runtime.test", "--output", str(output)]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["status"] == "passed"
    assert summary["evidence_path"] == str(output.resolve())
    assert ["plan" in call for call in calls] == [True, False, False]
    assert "run-group" in calls[1]
    assert "scripts/conversation_continuity_canary.py" in calls[2]
    assert calls[2][calls[2].index("--url") + 1] == "http://runtime.test"


def test_runtime_mode_fails_closed_on_invalid_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    evidence = _valid_evidence()
    evidence["answer"] = "forbidden-content"
    monkeypatch.setattr(
        module,
        "_run_command",
        _fake_runner(calls, evidence=evidence),
    )

    exit_code = module.main(
        [
            "--mode",
            "runtime",
            "--url",
            "http://runtime.test",
            "--output",
            str(tmp_path / "evidence.json"),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert summary["error_codes"] == ["continuity_evidence_invalid"]


def test_failed_subcommand_stops_the_sequence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        module,
        "_run_command",
        _fake_runner(calls, fail_on="plan"),
    )

    exit_code = module.main(["--mode", "runtime", "--url", "http://runtime.test"])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert summary["error_codes"] == ["quality_plan_failed"]
    assert len(calls) == 1


def test_runtime_requires_an_explicit_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "_run_command", _fake_runner(calls))

    exit_code = module.main(["--mode", "runtime"])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert summary["error_codes"] == ["runtime_url_required"]
    assert calls == []


def test_skill_metadata_is_utf8_chinese_and_matches_the_entrypoint() -> None:
    metadata = yaml.safe_load((SKILL / "agents/openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]

    assert interface == {
        "display_name": "验证直播对话连续性",
        "short_description": "稳定执行直播短期对话连续性的确定性契约与真实运行时哨兵",
        "default_prompt": "使用 $verify-conversation-continuity 选择并执行直播短期对话连续性回归。",
    }
