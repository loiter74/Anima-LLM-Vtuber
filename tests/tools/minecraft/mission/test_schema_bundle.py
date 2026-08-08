from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from animetta.tools.minecraft.mission import DiscoverGoal, models

ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = ROOT / "contracts" / "minecraft" / "mission" / "v1"


def _schema_module():
    return import_module("animetta.tools.minecraft.mission.schema")


def test_generated_mission_schema_bundle_and_digest_are_current() -> None:
    schema = _schema_module()
    expected = schema.build_schema_bundle()
    expected_digest = schema.schema_digest(expected)

    assert json.loads((CONTRACT_ROOT / "schema.json").read_text(encoding="utf-8")) == expected
    assert (CONTRACT_ROOT / "schema.sha256").read_text(encoding="utf-8").strip() == (
        expected_digest
    )


def test_golden_fixture_is_current_and_validates_every_versioned_contract() -> None:
    schema = _schema_module()
    expected = schema.build_golden_fixture()
    stored = json.loads((CONTRACT_ROOT / "fixtures" / "golden.json").read_text(encoding="utf-8"))

    assert stored == expected
    assert (
        models.MissionSpec.model_validate(stored["mission_spec"]).canonical_hash
        == (stored["canonical_hashes"]["mission_spec"])
    )
    assert models.MissionObjective.model_validate(stored["mission_objective"])
    assert DiscoverGoal.model_validate(stored["discover_goal"])
    assert models.AutonomyPolicy.model_validate(stored["autonomy_policy"])
    assert models.ExecutionPolicy.model_validate(stored["execution_policy"])
    assert models.GoalProposal.model_validate(stored["goal_proposal"])
    assert models.GoalAdmissionDecision.model_validate(stored["admission_decision"])
    assert models.StageDefinition.model_validate(stored["stage_definition"])
    assert models.StageIO.model_validate(stored["stage_io"])
    assert models.WalkthroughManifest.model_validate(stored["walkthrough_manifest"])
    assert models.MissionReport.model_validate(stored["mission_report"])
