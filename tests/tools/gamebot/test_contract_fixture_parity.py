"""Cross-runtime JSON fixtures must validate identically in Python and Node."""

from __future__ import annotations

import json
from pathlib import Path

from animetta.tools.gamebot.contracts import (
    CapabilityManifest,
    GameBotObservation,
    SkillExecutionResult,
    validate_receipt_chain,
)
from animetta.tools.minecraft.voyager.policy import VoyagerPolicy

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "gamebot_contract_v1.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_shared_v1_fixture_validates_and_preserves_node_hash_links() -> None:
    fixture = _fixture()
    manifest = CapabilityManifest.model_validate(fixture["manifest"])
    observation = GameBotObservation.model_validate(fixture["observation"])
    execution = SkillExecutionResult.model_validate(fixture["skill_execution"])

    chain = validate_receipt_chain(
        execution.receipts,
        session_id="session-1",
        task_id="task-1",
        runtime_id=manifest.runtime_id,
    )

    assert observation.runtime_id == manifest.runtime_id
    assert observation.content_hash == fixture["observation_hash"]
    assert chain.valid is True
    assert execution.receipts[1].previous_receipt_hash == execution.receipts[0].content_hash


def test_incompatible_fixture_is_rejected_by_python_controller_policy() -> None:
    fixture = _fixture()
    manifest = CapabilityManifest.model_validate(fixture["incompatible_manifest"])
    policy = VoyagerPolicy(
        supported_protocol="1.0",
        allowed_capabilities={"collect", "craft"},
    )

    report = policy.validate_manifest(manifest)

    assert report.allowed is False
    assert [violation.code for violation in report.violations] == [
        "INCOMPATIBLE_PROTOCOL"
    ]


def test_local_fixture_matches_sibling_node_runtime_when_present() -> None:
    node_fixture = (
        Path(__file__).resolve().parents[3].parent
        / "voyager-mc-bot"
        / "tests"
        / "fixtures"
        / FIXTURE.name
    )
    if not node_fixture.exists():
        return

    assert json.loads(node_fixture.read_text(encoding="utf-8")) == _fixture()
