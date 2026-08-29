from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
GROUP_JOBS = {
    "python-groups": "python_groups",
    "node-groups": "node_groups",
    "service-groups": "service_groups",
}


def _load_workflow(name: str) -> dict[str, Any]:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _commands(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _actions(job: dict[str, Any]) -> list[str]:
    return [step["uses"] for step in job["steps"] if "uses" in step]


def _action_step(job: dict[str, Any], action: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("uses") == action)


def _artifact_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v7"]


def test_ci_workflow_triggers_with_read_only_defaults_and_pr_only_cancellation() -> None:
    workflow = _load_workflow("quality.yml")
    text = (WORKFLOWS / "quality.yml").read_text(encoding="utf-8")

    assert workflow["name"] == "CI"
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {
        "plan",
        "python-groups",
        "node-groups",
        "service-groups",
        "docker-verify",
        "quality-gate",
        "package",
        "promote-main",
    }

    concurrency = workflow["concurrency"]
    assert "github.event.pull_request.number" in concurrency["group"]
    assert "github.run_id" in concurrency["group"]
    assert "github.event_name == 'pull_request'" in concurrency["cancel-in-progress"]
    assert "secrets." not in text


def test_plan_job_freezes_affected_plan_and_exports_matrices() -> None:
    workflow = _load_workflow("quality.yml")
    plan = workflow["jobs"]["plan"]
    commands = _commands(plan)

    checkout = _action_step(plan, "actions/checkout@v7")
    assert checkout["with"] == {"fetch-depth": "0"}
    assert "python -m pip install -r requirements-dev.txt" in commands
    assert {"pnpm/action-setup@v6", "actions/setup-node@v6"} <= set(_actions(plan))
    assert "python -m tooling.quality validate" in commands
    assert "python -m tooling.quality plan" in commands
    assert "--tier affected" in commands
    assert "--base-sha" in commands
    assert "--head-sha" in commands
    assert '--github-output "$GITHUB_OUTPUT"' in commands
    assert '--output "$QUALITY_PLAN"' in commands

    assert set(plan["outputs"]) == {
        "python_groups",
        "has_python",
        "node_groups",
        "has_node",
        "service_groups",
        "has_service",
        "docker_services",
        "has_docker_build",
        "plan_hash",
    }
    assert all("steps.quality-plan.outputs" in value for value in plan["outputs"].values())

    artifacts = _artifact_steps(plan)
    assert len(artifacts) == 1
    assert artifacts[0]["with"]["name"] == "quality-plan"
    assert artifacts[0]["with"]["retention-days"] == "14"
    assert "artifacts/test-impact/ci-plan.json" in artifacts[0]["with"]["path"]


def test_frozen_groups_run_in_dynamic_environment_matrices_without_result_cache() -> None:
    workflow = _load_workflow("quality.yml")

    for job_id, plan_output in GROUP_JOBS.items():
        job = workflow["jobs"][job_id]
        commands = _commands(job)
        strategy = job["strategy"]

        assert job["needs"] == "plan"
        assert strategy["fail-fast"] == "false"
        assert strategy["matrix"]["group"] == (
            "${{ fromJSON(needs.plan.outputs." + plan_output + ") }}"
        )
        assert "python -m tooling.quality run-group" in commands
        assert "--plan artifacts/test-impact/plan/ci-plan.json" in commands
        assert '--output "artifacts/test-impact/results/${{ matrix.group }}.json"' in commands
        assert "--cache off" in commands
        assert "--trust-scope" in commands

        artifacts = _artifact_steps(job)
        assert len(artifacts) == 1
        assert artifacts[0]["if"] == "always()"
        assert artifacts[0]["with"]["retention-days"] == "14"
        assert "quality-result-" in artifacts[0]["with"]["name"]
        artifact_paths = artifacts[0]["with"]["path"]
        assert "artifacts/test-impact/results/feedback/**" in artifact_paths
        assert "artifacts/test-impact/results/events/**" in artifact_paths

    python_actions = _actions(workflow["jobs"]["python-groups"])
    node_actions = _actions(workflow["jobs"]["node-groups"])
    service_actions = _actions(workflow["jobs"]["service-groups"])
    assert "actions/setup-python@v6" in python_actions
    assert {"pnpm/action-setup@v6", "actions/setup-node@v6"} <= set(node_actions)
    assert {
        "actions/setup-python@v6",
        "pnpm/action-setup@v6",
        "actions/setup-node@v6",
    } <= set(service_actions)


def test_pr_docker_build_and_aggregate_gate_follow_the_frozen_plan() -> None:
    workflow = _load_workflow("quality.yml")
    docker_job = workflow["jobs"]["docker-verify"]
    gate = workflow["jobs"]["quality-gate"]

    assert "github.event_name == 'pull_request'" in docker_job["if"]
    assert "needs.plan.outputs.has_docker_build == 'true'" in docker_job["if"]
    assert docker_job["env"] == {
        "ANIMETTA_REDIS_PASSWORD": "ci-build-only",
        "ANIMETTA_ACCESS_TOKEN": "ci-build-only",
    }
    assert "secrets." not in yaml.dump(docker_job)
    assert "python -m tooling.quality docker-build" in _commands(docker_job)
    assert "--plan artifacts/test-impact/plan/ci-plan.json" in _commands(docker_job)

    assert gate["name"] == "quality-gate"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {
        "plan",
        "python-groups",
        "node-groups",
        "service-groups",
        "docker-verify",
    }
    assert "python -m tooling.quality aggregate" in _commands(gate)
    assert "--results-dir artifacts/test-impact/collected/results" in _commands(gate)
    assert 'summary["status"] != "passed"' in _commands(gate)
    assert "needs.python-groups.result" in yaml.dump(gate)
    assert "needs.node-groups.result" in yaml.dump(gate)
    assert "needs.service-groups.result" in yaml.dump(gate)
    assert 'result" != "success"' in _commands(gate)
    result_download = _action_step(gate, "actions/download-artifact@v8")
    assert result_download["with"]["name"] == "quality-plan"
    assert any(step.get("with", {}).get("pattern") == "quality-result-*" for step in gate["steps"])
    assert all(
        step["with"]["retention-days"] == "14"
        for step in _artifact_steps(docker_job) + _artifact_steps(gate)
    )


def test_main_package_publishes_immutable_amd64_image_with_minimal_write_scope() -> None:
    workflow = _load_workflow("quality.yml")
    package = workflow["jobs"]["package"]
    commands = _commands(package)

    assert package["needs"] == "quality-gate"
    assert "github.event_name == 'push'" in package["if"]
    assert "github.ref == 'refs/heads/main'" in package["if"]
    assert package["permissions"] == {"contents": "read", "packages": "write"}
    checkout = _action_step(package, "actions/checkout@v7")
    assert checkout["with"] == {"fetch-depth": "0"}
    assert {
        "actions/setup-python@v6",
        "docker/setup-buildx-action@v4",
        "docker/login-action@v4",
        "docker/metadata-action@v6",
        "docker/build-push-action@v7",
    } <= set(_actions(package))

    login = _action_step(package, "docker/login-action@v4")["with"]
    assert login == {
        "registry": "ghcr.io",
        "username": "${{ github.actor }}",
        "password": "${{ github.token }}",
    }

    metadata = _action_step(package, "docker/metadata-action@v6")["with"]
    assert metadata["images"] == "ghcr.io/loiter74/animetta"
    assert "type=raw,value=sha-${{ github.sha }}" in metadata["tags"]
    assert "type=raw,value=main" not in metadata["tags"]
    assert (
        "org.opencontainers.image.created=${{ steps.fingerprint.outputs.created }}"
        in metadata["labels"]
    )
    assert "org.opencontainers.image.revision=${{ github.sha }}" in metadata["labels"]
    assert "org.opencontainers.image.source=" in metadata["labels"]

    build = _action_step(package, "docker/build-push-action@v7")["with"]
    assert build["platforms"] == "linux/amd64"
    assert build["push"] == "true"
    assert build["provenance"] == "mode=min"
    assert build["cache-from"] == "type=gha"
    assert build["cache-to"] == "type=gha,mode=max"
    assert (
        "index:org.opencontainers.image.created=${{ steps.fingerprint.outputs.created }}"
        in build["annotations"]
    )
    assert "index:org.opencontainers.image.revision=${{ github.sha }}" in build["annotations"]
    assert "index:org.opencontainers.image.source=" in build["annotations"]
    assert (
        "ANIMETTA_BUILD_FINGERPRINT=${{ steps.fingerprint.outputs.fingerprint }}"
        in build["build-args"]
    )
    assert "ANIMETTA_BUILD_FINGERPRINT=${{ github.sha }}" not in build["build-args"]
    assert "steps.meta.outputs.tags" in build["tags"]
    assert "steps.meta.outputs.labels" in build["labels"]
    assert "python -m tooling.quality plan" in commands
    assert "--paths Dockerfile" in commands
    assert "package-plan.json" in commands
    assert "created=$(date -u" in commands
    assert 'if action["service"] == "animetta"' in commands
    assert "len(actions) != 1" in commands
    assert 'output.write(f"fingerprint={fingerprint}' in commands
    assert "steps.build.outputs.digest" in commands
    assert (
        "anima-deploy --image ghcr.io/loiter74/animetta@${{ steps.build.outputs.digest }}"
        in commands
    )
    assert "anima-deploy --image ghcr.io/loiter74/animetta:sha-${GITHUB_SHA}" in commands


def test_main_tag_promotion_is_serialized_and_never_rebuilds_the_image() -> None:
    workflow = _load_workflow("quality.yml")
    promotion = workflow["jobs"]["promote-main"]
    commands = _commands(promotion)

    assert promotion["needs"] == "package"
    assert promotion["permissions"] == {"contents": "read", "packages": "write"}
    assert promotion["concurrency"] == {
        "group": "animetta-ghcr-main-promotion",
        "cancel-in-progress": "false",
    }
    checkout = _action_step(promotion, "actions/checkout@v7")
    assert checkout["with"] == {"fetch-depth": "0"}
    assert "docker/build-push-action" not in yaml.dump(promotion)
    assert "docker buildx imagetools inspect" in commands
    assert "--raw > current-main-manifest.json" in commands
    assert "org.opencontainers.image.revision" in commands
    assert 'manifest.get("annotations")' in commands
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" "$current_revision"' in commands
    assert "docker buildx imagetools create" in commands
    assert (
        "index:org.opencontainers.image.created=${{ needs.package.outputs.image_created }}"
        in commands
    )
    assert "index:org.opencontainers.image.revision=$GITHUB_SHA" in commands
    assert "index:org.opencontainers.image.source=${{ github.server_url }}" in commands
    assert "needs.package.outputs.image_digest" in commands
    assert '--tag "$IMAGE:main"' in commands


def test_dependency_caches_are_limited_to_pip_pnpm_and_buildkit() -> None:
    workflow = _load_workflow("quality.yml")
    text = (WORKFLOWS / "quality.yml").read_text(encoding="utf-8")

    assert "actions/cache@" not in text
    assert ".quality-cache" not in text
    assert "cache: pip" in text
    assert "cache: pnpm" in text
    assert "cache-from: type=gha" in text
    assert "cache-to: type=gha,mode=max" in text

    write_jobs = {"package", "promote-main"}
    for job_id, job in workflow["jobs"].items():
        if job_id in write_jobs:
            assert job["permissions"] == {"contents": "read", "packages": "write"}
            continue
        assert "packages" not in job.get("permissions", {})
        assert "github.token" not in yaml.dump(job)


def test_deployment_is_manual_and_does_not_retest() -> None:
    deployment = _load_workflow("deploy-zeabur.yml")
    text = (WORKFLOWS / "deploy-zeabur.yml").read_text(encoding="utf-8")

    assert set(deployment["on"]) == {"workflow_dispatch"}
    assert "workflow_run" not in text
    assert "python -m pytest" not in text
    assert "Run Tests" not in text


def test_legacy_duplicate_test_workflows_are_removed() -> None:
    assert not (WORKFLOWS / "test.yml").exists()
    assert not (WORKFLOWS / "frontend.yml").exists()
