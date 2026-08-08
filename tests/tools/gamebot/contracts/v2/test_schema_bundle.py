from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from animetta.tools.gamebot.contracts.v2 import (
    ActionReceipt,
    ActionRequest,
    ActionStatus,
    AdvancementObservedEvent,
    BudgetVector,
    CancellationAck,
    CancellationRequest,
    CombatTerminalEvidence,
    Observation,
    RegionInspection,
    RegionInspectionRequest,
    RuntimeHealth,
    RuntimeManifest,
    RuntimeProtocolError,
    canonical_json_hash,
)
from animetta.tools.gamebot.contracts.v2.schema import build_schema_bundle

ROOT = Path(__file__).resolve().parents[5]
CONTRACT_ROOT = ROOT / "contracts" / "gamebot" / "v2"

MODELS = {
    "RuntimeManifest": RuntimeManifest,
    "ActionRequest": ActionRequest,
    "Observation": Observation,
    "ActionReceipt": ActionReceipt,
    "RuntimeProtocolError": RuntimeProtocolError,
    "CancellationRequest": CancellationRequest,
    "CancellationAck": CancellationAck,
    "BudgetVector": BudgetVector,
    "RuntimeHealth": RuntimeHealth,
    "ActionStatus": ActionStatus,
    "CombatTerminalEvidence": CombatTerminalEvidence,
    "RegionInspectionRequest": RegionInspectionRequest,
    "RegionInspection": RegionInspection,
    "AdvancementObservedEvent": AdvancementObservedEvent,
}


def test_checked_in_schema_is_valid_and_matches_python_models() -> None:
    schema = json.loads((CONTRACT_ROOT / "schema.json").read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    assert schema == build_schema_bundle()
    assert set(MODELS).issubset(schema["$defs"])
    assert (CONTRACT_ROOT / "schema.sha256").read_text(encoding="utf-8").strip() == (
        canonical_json_hash(schema)
    )


def test_golden_messages_validate_in_json_schema_and_pydantic() -> None:
    schema = json.loads((CONTRACT_ROOT / "schema.json").read_text(encoding="utf-8"))
    fixture = json.loads((CONTRACT_ROOT / "fixtures" / "golden.json").read_text(encoding="utf-8"))

    assert fixture["schema_digest"] == canonical_json_hash(schema)
    for model_name, model in MODELS.items():
        payload = fixture["messages"][model_name]
        validator = Draft202012Validator(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": schema["$defs"],
                "$ref": f"#/$defs/{model_name}",
            }
        )
        validator.validate(payload)
        assert model.model_validate(payload).model_dump(mode="json") == payload
