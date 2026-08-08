"""Deterministic JSON-schema export for the canonical GameBot v2 bundle."""

from __future__ import annotations

from typing import Any

from pydantic.json_schema import models_json_schema

from .budget import BudgetVector
from .errors import RuntimeProtocolError
from .evidence import AdvancementObservedEvent, RegionInspection
from .manifest import RuntimeManifest
from .observations import Observation
from .receipts import (
    ActionReceipt,
    ActionStatus,
    CancellationAck,
    CombatTerminalEvidence,
    RuntimeHealth,
)
from .requests import ActionRequest, CancellationRequest, RegionInspectionRequest

_PUBLIC_MODELS = (
    RuntimeManifest,
    ActionRequest,
    Observation,
    ActionReceipt,
    RuntimeProtocolError,
    CancellationRequest,
    CancellationAck,
    BudgetVector,
    RuntimeHealth,
    ActionStatus,
    CombatTerminalEvidence,
    RegionInspectionRequest,
    RegionInspection,
    AdvancementObservedEvent,
)


def build_schema_bundle() -> dict[str, Any]:
    """Build the checked-in Draft 2020-12 schema bundle."""

    _, schema = models_json_schema(
        [(model, "validation") for model in _PUBLIC_MODELS],
        title="Animetta GameBot v2 canonical contract",
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://animetta.local/contracts/gamebot/v2/schema.json",
        "schema_version": "2",
        **schema,
    }
