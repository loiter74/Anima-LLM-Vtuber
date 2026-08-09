#!/usr/bin/env python3
"""Generate canonical GameBot v2 JSON schema and golden messages."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from animetta.tools.gamebot.contracts.v2 import (  # noqa: E402
    ActionInspectionState,
    ActionReceipt,
    ActionRequest,
    ActionStatus,
    AdvancementObservedEvent,
    BudgetVector,
    CancellationAck,
    CancellationRequest,
    CapabilityDefinition,
    CapabilityGuarantees,
    CombatTerminalEvidence,
    DiscoverableBlock,
    DiscoverableEntity,
    EnvironmentProfile,
    Observation,
    Position,
    ReceiptOutcome,
    RegionBounds,
    RegionInspection,
    RegionInspectionRequest,
    RuntimeHealth,
    RuntimeManifest,
    RuntimeProtocolError,
    WorldIdentitySnapshot,
    canonical_json_hash,
)
from animetta.tools.gamebot.contracts.v2.schema import build_schema_bundle  # noqa: E402


def _budget(**overrides: int | float) -> BudgetVector:
    values: dict[str, Any] = {
        "max_actions": 4,
        "max_strategy_attempts": 1,
        "max_travel_distance": 32.0,
        "max_blocks_changed": 4,
        "max_damage_taken": 2.0,
    }
    values.update(overrides)
    return BudgetVector(**values)


def _profile() -> EnvironmentProfile:
    return EnvironmentProfile(
        runtime_protocol="2.0",
        minecraft_version="1.21.1",
        capability_schema_digest="a" * 64,
        skill_api_version="1",
        policy_version="1",
        server_identity_hash="b" * 64,
        world_identity_hash="c" * 64,
        dimension="minecraft:overworld",
        modset_digest="d" * 64,
    )


def _world() -> WorldIdentitySnapshot:
    profile = _profile()
    return WorldIdentitySnapshot(
        runtime_instance_id="runtime-instance-1",
        server_identity_hash=profile.server_identity_hash,
        world_identity_hash=profile.world_identity_hash,
        dimension=profile.dimension,
    )


def _error() -> RuntimeProtocolError:
    return RuntimeProtocolError(
        code="RESOURCE_NOT_FOUND",
        message="tree missing",
        phase="runtime",
        command_id="command-1",
        step_id="step-1",
        correlation_id="correlation-1",
        outcome_known=True,
        world_may_have_changed=False,
        caller_may_resubmit=False,
        operator_action="inspect status",
    )


def _receipt() -> ActionReceipt:
    receipt = ActionReceipt(
        receipt_id="receipt-1",
        command_id="command-1",
        step_id="step-1",
        correlation_id="correlation-1",
        runtime_instance_id="runtime-instance-1",
        capability="collect",
        parameter_hash=canonical_json_hash({"count": 1}),
        action_sequence=8,
        started_at_ms=1_799_999_999_100,
        finished_at_ms=1_799_999_999_900,
        started_tick=43,
        finished_tick=48,
        outcome=ReceiptOutcome.SUCCESS,
        post_observation="stable",
        reconciliation="accepted",
        goal_verification="unknown",
        reconciliation_error=None,
        settlement_trace=(),
        before_observation_hash="f" * 64,
        after_observation_hash="e" * 64,
        explained_mutations=[{"kind": "inventory", "subject": "oak_log", "delta": 1.0}],
        budget_usage=_budget(max_actions=1, max_travel_distance=2.0),
        content_hash="1" * 64,
    )
    return receipt.model_copy(
        update={
            "content_hash": canonical_json_hash(
                receipt.model_dump(mode="json", exclude={"content_hash"})
            )
        }
    )


def _messages() -> dict[str, Any]:
    receipt = _receipt()
    return {
        "RuntimeManifest": RuntimeManifest(
            runtime_instance_id="runtime-instance-1",
            profile=_profile(),
            guarantees=CapabilityGuarantees(
                single_flight=True,
                correlation_idempotency=True,
                cooperative_cancellation=True,
                action_budget_enforcement=True,
                receipt_chains=True,
                correlation_inspection=True,
            ),
            capabilities=[
                CapabilityDefinition(
                    name="collect",
                    risk="survival_safe",
                    effect_class="state_changing",
                    parameters_schema={
                        "type": "object",
                        "properties": {"count": {"type": "integer", "minimum": 1}},
                        "required": ["count"],
                        "additionalProperties": False,
                    },
                    receipt_schema_version="2",
                    requires_post_observation=True,
                    maximum_cost=_budget(max_actions=1),
                ),
                CapabilityDefinition(
                    name="attack",
                    risk="survival_safe",
                    effect_class="state_changing",
                    parameters_schema={
                        "type": "object",
                        "properties": {"target_entity_id": {"type": "string", "minLength": 1}},
                        "required": ["target_entity_id"],
                        "additionalProperties": False,
                    },
                    receipt_schema_version="2",
                    requires_post_observation=True,
                    maximum_cost=_budget(max_actions=1, max_damage_taken=4),
                ),
                CapabilityDefinition(
                    name="inspect_region",
                    risk="read_only",
                    effect_class="read_only",
                    parameters_schema={
                        "type": "object",
                        "properties": {
                            "bounds": {"type": "object"},
                            "maximum_volume": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 4096,
                            },
                        },
                        "required": ["bounds", "maximum_volume"],
                        "additionalProperties": False,
                    },
                    receipt_schema_version="2",
                    requires_post_observation=False,
                    maximum_cost=_budget(max_actions=1),
                ),
            ],
        ),
        "ActionRequest": ActionRequest(
            transport_id="transport-1",
            command_id="command-1",
            step_id="step-1",
            correlation_id="correlation-1",
            runtime_instance_id="runtime-instance-1",
            capability="collect",
            parameters={"count": 1},
            remaining_budget=_budget(),
            deadline_ms=1_800_000_000_000,
        ),
        "Observation": Observation(
            observation_id="observation-1",
            correlation_id="correlation-observe-1",
            runtime_instance_id="runtime-instance-1",
            captured_at_ms=1_799_999_999_000,
            tick=42,
            action_sequence=7,
            content_hash="e" * 64,
            profile=_profile(),
            world_identity=_world(),
            position={"x": 0.0, "y": 64.0, "z": 0.0},
            health=20.0,
            food=20,
            inventory={"oak_log": 1},
            equipment={},
            environment={"weather": "clear"},
            biome="minecraft:plains",
            active_advancements=["minecraft:story/root"],
            visible_blocks=[
                DiscoverableBlock(
                    block_id="minecraft:copper_ore",
                    position=Position(x=3, y=62, z=4),
                )
            ],
            visible_entities=[
                DiscoverableEntity(
                    entity_id="entity-zombie-001",
                    entity_type="minecraft:zombie",
                    position=Position(x=8, y=64, z=2),
                    health=20,
                )
            ],
        ),
        "ActionReceipt": receipt,
        "RuntimeProtocolError": _error(),
        "CancellationRequest": CancellationRequest(
            runtime_instance_id="runtime-instance-1",
            correlation_id="correlation-1",
            reason="operator stop",
        ),
        "CancellationAck": CancellationAck(
            runtime_instance_id="runtime-instance-1",
            correlation_id="correlation-1",
            accepted=True,
            accepted_at_ms=1_799_999_999_500,
        ),
        "BudgetVector": _budget(),
        "RuntimeHealth": RuntimeHealth(
            ready=True,
            busy=False,
            runtime_instance_id="runtime-instance-1",
            last_completed_action_sequence=8,
        ),
        "ActionStatus": ActionStatus(
            runtime_instance_id="runtime-instance-1",
            correlation_id="correlation-1",
            state=ActionInspectionState.TERMINAL,
            request_hash="2" * 64,
            receipt=receipt,
            retained_until_ms=1_800_100_000_000,
        ),
        "CombatTerminalEvidence": CombatTerminalEvidence(
            target_entity_id="entity-zombie-001",
            target_entity_type="minecraft:zombie",
            outcome="defeated",
            bot_health_before=20,
            bot_health_after=17,
            target_health_before=20,
            target_health_after=0,
            started_tick=100,
            finished_tick=124,
        ),
        "RegionInspectionRequest": RegionInspectionRequest(
            transport_id="transport-region-1",
            command_id="command-region-1",
            step_id="inspect-shelter",
            correlation_id="correlation-region-1",
            runtime_instance_id="runtime-instance-1",
            bounds=RegionBounds(
                min=Position(x=0, y=60, z=0),
                max=Position(x=3, y=63, z=3),
            ),
            maximum_volume=64,
            deadline_ms=1_800_000_000_000,
        ),
        "RegionInspection": RegionInspection(
            inspection_id="inspection-1",
            correlation_id="correlation-region-1",
            runtime_instance_id="runtime-instance-1",
            world_identity=_world(),
            captured_at_ms=1_799_999_999_900,
            tick=200,
            observation_id="observation-region-001",
            observation_hash="e" * 64,
            bounds=RegionBounds(
                min=Position(x=0, y=60, z=0),
                max=Position(x=3, y=63, z=3),
            ),
            blocks={"0,60,0": "minecraft:oak_planks"},
            content_hash="4" * 64,
        ),
        "AdvancementObservedEvent": AdvancementObservedEvent(
            event_id="advancement-event-001",
            runtime_instance_id="runtime-instance-1",
            world_identity=_world(),
            advancement_id="minecraft:story/mine_stone",
            action="add",
            observation_id="observation-advancement-001",
            observation_hash="e" * 64,
            observed_at_ms=1_799_999_999_950,
            tick=220,
            source="version_adapter",
            content_hash="5" * 64,
        ),
    }


def _schema_type(schema: dict[str, Any], *, indent: int = 0) -> str:
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", maxsplit=1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if alternatives:
        return " | ".join(_schema_type(item, indent=indent) for item in alternatives)
    schema_type = schema.get("type")
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        return f"ReadonlyArray<{_schema_type(schema.get('items', {}), indent=indent)}>"
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not properties:
            additional = schema.get("additionalProperties", True)
            value_type = (
                "unknown" if additional is True else _schema_type(additional, indent=indent)
            )
            return f"Readonly<Record<string, {value_type}>>"
        padding = " " * indent
        child_padding = " " * (indent + 2)
        lines = ["{"]
        for name, definition in properties.items():
            optional = "" if name in required else "?"
            lines.append(
                f"{child_padding}readonly {name}{optional}: "
                f"{_schema_type(definition, indent=indent + 2)};"
            )
        lines.append(f"{padding}}}")
        return "\n".join(lines)
    return "unknown"


def _typescript_declarations(schema: dict[str, Any], digest: str) -> str:
    lines = [
        "// Generated from contracts/gamebot/v2/schema.json; do not edit.",
        f"// schema-digest: {digest}",
        "",
    ]
    for name, definition in sorted(schema["$defs"].items()):
        lines.append(f"export type {name} = {_schema_type(definition)};")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    contract_root = ROOT / "contracts" / "gamebot" / "v2"
    fixture_root = contract_root / "fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    schema = build_schema_bundle()
    digest = canonical_json_hash(schema)
    (contract_root / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (contract_root / "schema.sha256").write_text(f"{digest}\n", encoding="utf-8")
    (contract_root / "types.d.ts").write_text(
        _typescript_declarations(schema, digest),
        encoding="utf-8",
    )
    fixture = {
        "schema_digest": digest,
        "messages": {name: model.model_dump(mode="json") for name, model in _messages().items()},
    }
    (fixture_root / "golden.json").write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
