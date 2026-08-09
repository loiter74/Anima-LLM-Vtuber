"""Anima's local GameBot contract fixtures validate consistently."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts import (
    CapabilityManifest,
    GameBotObservation,
    SkillExecutionResult,
    validate_receipt_chain,
)
from animetta.tools.gamebot.contracts.v2 import RuntimeManifest

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


def test_v1_fixture_cannot_be_used_as_a_v2_readiness_manifest() -> None:
    fixture = _fixture()

    with pytest.raises(ValidationError):
        RuntimeManifest.model_validate(fixture["incompatible_manifest"])
