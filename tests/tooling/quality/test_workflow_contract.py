from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load_workflow(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_ci_workflow_is_minimal_and_read_only() -> None:
    workflow = _load_workflow("quality.yml")
    text = (WORKFLOWS / "quality.yml").read_text(encoding="utf-8")

    assert workflow["name"] == "CI"
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"validate"}

    job = workflow["jobs"]["validate"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "5"
    assert [step["uses"] for step in job["steps"] if "uses" in step] == [
        "actions/checkout@v4",
        "actions/setup-python@v5",
    ]
    assert job["steps"][1]["with"] == {"python-version-file": ".python-version"}
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python -m pip install pydantic pyyaml" in commands
    assert "python -m tooling.quality validate" in commands

    for forbidden in (
        "actions/cache@",
        "actions/upload-artifact@",
        "docker",
        "matrix",
        "playwright",
        "pnpm",
        "secrets.",
        "self-hosted",
    ):
        assert forbidden not in text


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
