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
    assert "github.event.pull_request.number || github.run_id" in workflow["concurrency"]["group"]
    assert set(workflow["jobs"]) == {
        "plan",
        "preflight",
        "python",
        "node",
        "service",
        "docker",
        "release-runtime",
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
        assert matrix == {"group": f"${{{{ fromJSON(needs.plan.outputs.{output_name}) }}}}"}
        commands = "\n".join(step.get("run", "") for step in job["steps"] if isinstance(step, dict))
        assert "tooling.quality run-group" in commands
        assert "matrix.group" in commands
        assert "ruff check" not in commands
        assert "eslint" not in commands
        assert "prettier" not in commands

    for job_id in ("python", "node", "service"):
        assert workflow["jobs"][job_id]["continue-on-error"] == "true"

    assert workflow["jobs"]["service"]["env"] == {
        "ANIMETTA_PROFILE": "test",
        "HF_CACHE_DIR": "/tmp/animetta-ci-hf",
        "ALICE_REF_AUDIO": "/tmp/animetta-ci-alice.wav",
    }
    service_commands = "\n".join(
        step.get("run", "")
        for step in workflow["jobs"]["service"]["steps"]
        if isinstance(step, dict)
    )
    assert "mkdir -p /tmp/animetta-ci-hf" in service_commands
    assert "touch /tmp/animetta-ci-alice.wav" in service_commands


def test_quality_workflow_scopes_cache_by_trust_and_keeps_release_cold() -> None:
    text = (WORKFLOWS / "quality.yml").read_text(encoding="utf-8")
    workflow = _load_workflow("quality.yml")
    plan = workflow["jobs"]["plan"]

    assert {"cache_mode", "trust_scope", "cache_trust"} <= set(plan["outputs"])
    assert 'echo "cache_mode=off"' in text
    assert 'echo "trust_scope=release"' in text
    assert 'echo "cache_mode=read-write"' in text
    assert 'echo "trust_scope=pr"' in text
    assert "pr-${{ github.event.pull_request.number }}" in text

    for job_id in ("python", "node"):
        job = workflow["jobs"][job_id]
        cache_steps = [
            step
            for step in job["steps"]
            if isinstance(step, dict) and step.get("uses") == "actions/cache@v4"
        ]
        assert len(cache_steps) == 1
        cache_step = cache_steps[0]
        assert cache_step["if"] == "needs.plan.outputs.cache_mode == 'read-write'"
        assert cache_step["with"]["path"] == "artifacts/test-impact/cache-v1"
        assert "needs.plan.outputs.cache_trust" in cache_step["with"]["key"]

    for job_id in ("python", "node", "service"):
        commands = "\n".join(
            step.get("run", "")
            for step in workflow["jobs"][job_id]["steps"]
            if isinstance(step, dict)
        )
        assert '--cache "${{ needs.plan.outputs.cache_mode }}"' in commands
        assert '--trust-scope "${{ needs.plan.outputs.trust_scope }}"' in commands

    docker_job = workflow["jobs"]["docker"]
    assert docker_job["needs"] == "plan"
    assert "needs.plan.outputs.has_docker_build == 'true'" in docker_job["if"]
    assert "needs.plan.outputs.tier != 'full'" in docker_job["if"]
    assert "needs.plan.outputs.tier != 'nightly'" in docker_job["if"]
    docker_commands = "\n".join(
        step.get("run", "") for step in docker_job["steps"] if isinstance(step, dict)
    )
    assert "tooling.quality docker-build" in docker_commands
    assert "--plan artifacts/test-impact/ci/plan.json" in docker_commands

    release_job = workflow["jobs"]["release-runtime"]
    assert release_job["needs"] == "plan"
    assert "needs.plan.outputs.tier == 'full'" in release_job["if"]
    assert "needs.plan.outputs.tier == 'nightly'" in release_job["if"]
    assert set(release_job["runs-on"]) == {
        "self-hosted",
        "windows",
        "gpu",
        "animetta-release",
    }
    release_commands = "\n".join(
        step.get("run", "") for step in release_job["steps"] if isinstance(step, dict)
    )
    assert "scripts/release_runtime_gate.py" in release_commands
    assert "playwright install chromium" in release_commands
    assert "docker compose down --remove-orphans" in release_commands
    assert "docker compose -f docker-compose.qwen.yml logs --no-color" in release_commands
    assert "docker compose -f docker-compose.qwen.yml down --remove-orphans" not in release_commands
    assert set(release_job["env"]) == {
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MIMO_API_KEY",
        "QWEN_TTS_API_KEY",
        "HF_CACHE_DIR",
        "ALICE_REF_AUDIO",
    }


def test_quality_gate_always_aggregates_persistent_evidence() -> None:
    workflow = _load_workflow("quality.yml")
    gate = workflow["jobs"]["quality-gate"]

    assert "always()" in gate["if"]
    assert set(gate["needs"]) == {
        "plan",
        "python",
        "node",
        "service",
        "docker",
        "release-runtime",
    }
    gate_commands = "\n".join(
        step.get("run", "") for step in gate["steps"] if isinstance(step, dict)
    )
    assert "tooling.quality aggregate" in gate_commands
    assert "needs.docker.result" in gate_commands
    assert "needs.release-runtime.result" in gate_commands

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
