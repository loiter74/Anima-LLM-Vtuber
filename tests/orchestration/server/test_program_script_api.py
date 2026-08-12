from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.testclient import TestClient

from animetta.orchestration.server.program_script_api import get_program_script_routes
from animetta.services.program_script import (
    ProgramReplayCoordinator,
    ProgramScriptRepository,
    ProgramScriptRunner,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_dashboard_can_copy_edit_validate_and_publish(tmp_path: Path) -> None:
    repository = ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    runner = ProgramScriptRunner(repository)
    replay = ProgramReplayCoordinator()
    client = TestClient(Starlette(routes=get_program_script_routes(repository, runner, replay)))

    listed = client.get("/api/program-scripts")
    assert listed.status_code == 200
    assert listed.json()["scripts"][0]["id"] == "aura-debut-memory"

    copied = client.post(
        "/api/program-scripts/aura-debut-memory/versions/1/duplicate",
        json={"new_id": "dashboard-copy", "title": "Dashboard 副本"},
    )
    assert copied.status_code == 201
    draft = copied.json()
    draft["script"]["description"] = "在结构化编辑器中修改"

    saved = client.put(
        "/api/program-scripts/drafts/dashboard-copy",
        json={"revision": draft["revision"], "script": draft["script"]},
    )
    assert saved.status_code == 200

    validation = client.post("/api/program-scripts/drafts/dashboard-copy/validate")
    assert validation.json() == {"valid": True, "issues": []}

    published = client.post(
        "/api/program-scripts/drafts/dashboard-copy/publish",
        json={"revision": saved.json()["revision"]},
    )
    assert published.status_code == 201
    assert published.json()["version"] == 1
    assert len(published.json()["content_hash"]) == 64

    immutable = client.get("/api/program-scripts/dashboard-copy/versions/1")
    assert immutable.json()["script"]["description"] == "在结构化编辑器中修改"


def test_publish_rejects_aura_false_premise_that_can_be_true(tmp_path: Path) -> None:
    repository = ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    runner = ProgramScriptRunner(repository)
    replay = ProgramReplayCoordinator()
    client = TestClient(Starlette(routes=get_program_script_routes(repository, runner, replay)))
    draft = client.post(
        "/api/program-scripts/aura-debut-memory/versions/1/duplicate",
        json={"new_id": "invalid-aura"},
    ).json()
    draft["script"]["template"] = "aura_debut_memory"
    weekend = draft["script"]["option_sets"]["weekend"][0]
    weekend["label"] = "周末爬山"
    weekend["aliases"] = ["周末爬山"]
    weekend["danmaku"] = "这个周末我要去爬山"
    saved = client.put(
        "/api/program-scripts/drafts/invalid-aura",
        json={"revision": draft["revision"], "script": draft["script"]},
    ).json()

    validation = client.post("/api/program-scripts/drafts/invalid-aura/validate")
    assert validation.json()["valid"] is False
    assert "aura_false_weekend" in {issue["code"] for issue in validation.json()["issues"]}

    publish = client.post(
        "/api/program-scripts/drafts/invalid-aura/publish",
        json={"revision": saved["revision"]},
    )
    assert publish.status_code == 422
    assert publish.json()["error_code"] == "validation_failed"


def test_duplicate_returns_field_level_validation_errors(tmp_path: Path) -> None:
    repository = ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )
    client = TestClient(
        Starlette(
            routes=get_program_script_routes(
                repository,
                ProgramScriptRunner(repository),
                ProgramReplayCoordinator(),
            )
        )
    )

    response = client.post(
        "/api/program-scripts/aura-debut-memory/versions/1/duplicate",
        json={"new_id": "Not valid"},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"
    assert any("id" in issue["loc"] for issue in response.json()["issues"])
