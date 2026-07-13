from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load_workflow(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_quality_workflow_has_authoritative_event_and_permission_contract() -> None:
    workflow = _load_workflow("quality.yml")

    assert workflow["name"] == "Quality"
    assert set(workflow["on"]) == {
        "pull_request",
        "push",
        "schedule",
        "workflow_dispatch",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )
    assert "github.event.pull_request.number || github.run_id" in workflow[
        "concurrency"
    ]["group"]
    assert set(workflow["jobs"]) == {
        "plan",
        "python",
        "node",
        "service",
        "quality-gate",
    }


def test_quality_workflow_maps_events_to_tiers_and_group_id_matrices() -> None:
    text = (WORKFLOWS / "quality.yml").read_text(encoding="utf-8")
    workflow = _load_workflow("quality.yml")

    assert 'TIER="affected"' in text
    assert 'TIER="full"' in text
    assert 'TIER="nightly"' in text
    assert "github.event.inputs.tier" in text
    assert "--base-sha" in text and "--head-sha" in text
    assert "paths:" not in text

    for job_id, output_name in (
        ("python", "python_groups"),
        ("node", "node_groups"),
        ("service", "service_groups"),
    ):
        job = workflow["jobs"][job_id]
        matrix = job["strategy"]["matrix"]
        assert matrix == {
            "group": f"${{{{ fromJSON(needs.plan.outputs.{output_name}) }}}}"
        }
        commands = "\n".join(
            step.get("run", "") for step in job["steps"] if isinstance(step, dict)
        )
        assert "tooling.quality run-group" in commands
        assert "matrix.group" in commands

    for job_id in ("python", "node", "service"):
        assert workflow["jobs"][job_id]["continue-on-error"] == "true"


def test_quality_gate_always_aggregates_persistent_evidence() -> None:
    workflow = _load_workflow("quality.yml")
    gate = workflow["jobs"]["quality-gate"]

    assert "always()" in gate["if"]
    assert set(gate["needs"]) == {"plan", "python", "node", "service"}
    gate_commands = "\n".join(
        step.get("run", "") for step in gate["steps"] if isinstance(step, dict)
    )
    assert "tooling.quality aggregate" in gate_commands

    upload_steps = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if isinstance(step, dict) and step.get("uses") == "actions/upload-artifact@v4"
    ]
    assert upload_steps
    assert all("always()" in step.get("if", "") for step in upload_steps)
    assert all(int(step["with"]["retention-days"]) >= 7 for step in upload_steps)

    text = (WORKFLOWS / "quality.yml").read_text(encoding="utf-8")
    assert "quality-plan-${{ github.run_id }}-${{ github.run_attempt }}" in text
    assert "pattern: quality-result-*-${{ github.run_attempt }}" in text
    assert "Traceback|ERROR|CRITICAL|FATAL" in text
    assert 'rm -f "artifacts/test-impact/ci/results/${{ matrix.group }}.json"' in text


def test_legacy_duplicate_test_workflows_are_removed() -> None:
    assert not (WORKFLOWS / "test.yml").exists()
    assert not (WORKFLOWS / "frontend.yml").exists()


def test_deployment_consumes_successful_quality_run_without_retesting() -> None:
    deployment = _load_workflow("deploy-zeabur.yml")
    text = (WORKFLOWS / "deploy-zeabur.yml").read_text(encoding="utf-8")

    assert set(deployment["on"]) == {"workflow_run"}
    assert deployment["on"]["workflow_run"]["workflows"] == ["Quality"]
    assert deployment["on"]["workflow_run"]["types"] == ["completed"]
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.event == 'push'" in text
    assert "github.event.workflow_run.head_sha" in text
    assert "python -m pytest" not in text
    assert "Run Tests" not in text
