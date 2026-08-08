"""Typed GameBot v2 adapter contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from animetta.tools.gamebot.contracts.v2 import (
    ActionInspectionRequest,
    ActionRequest,
    CancellationRequest,
    ObservationRequest,
    RegionInspectionRequest,
)
from animetta.tools.minecraft.core.adapter import (
    GameBotRuntimeError,
    MinecraftGameBotV2Adapter,
)

ROOT = Path(__file__).resolve().parents[4]
GOLDEN = json.loads(
    (ROOT / "contracts" / "gamebot" / "v2" / "fixtures" / "golden.json").read_text(encoding="utf-8")
)["messages"]


async def test_manifest_validation_binds_runtime_instance() -> None:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command.return_value = {
        "status": "success",
        "result": GOLDEN["RuntimeManifest"],
    }
    adapter = MinecraftGameBotV2Adapter(bridge)

    manifest = await adapter.get_manifest()

    assert adapter.runtime_instance_id == manifest.runtime_instance_id
    bridge.send_command.assert_awaited_once_with("gamebot_v2_manifest", {}, timeout=5.0)


async def test_adapter_sends_exact_v2_models_and_parses_results() -> None:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command = AsyncMock(
        side_effect=[
            {"status": "success", "result": GOLDEN["RuntimeManifest"]},
            {"status": "success", "result": GOLDEN["Observation"]},
            {"status": "success", "result": GOLDEN["RegionInspection"]},
            {"status": "success", "result": GOLDEN["ActionReceipt"]},
            {"status": "success", "result": GOLDEN["ActionStatus"]},
            {"status": "success", "result": GOLDEN["CancellationAck"]},
            {"status": "success", "result": GOLDEN["RuntimeHealth"]},
        ]
    )
    adapter = MinecraftGameBotV2Adapter(bridge)
    await adapter.get_manifest()

    observation_request = ObservationRequest(
        transport_id="transport-observe-1",
        command_id="command-1",
        step_id="step-observe-1",
        correlation_id="correlation-observe-1",
        runtime_instance_id="runtime-instance-1",
        deadline_ms=1_800_000_000_000,
    )
    action_request = ActionRequest.model_validate(GOLDEN["ActionRequest"])
    region_request = RegionInspectionRequest.model_validate(GOLDEN["RegionInspectionRequest"])
    inspection_request = ActionInspectionRequest(
        runtime_instance_id="runtime-instance-1",
        correlation_id="correlation-1",
    )
    cancellation_request = CancellationRequest.model_validate(GOLDEN["CancellationRequest"])

    observation = await adapter.observe(observation_request)
    region = await adapter.inspect_region(region_request)
    receipt = await adapter.execute_action(action_request, timeout=12.0)
    status = await adapter.inspect_action(inspection_request)
    cancellation = await adapter.cancel_action(cancellation_request)
    health = await adapter.health()

    assert observation.runtime_instance_id == adapter.runtime_instance_id
    assert region.runtime_instance_id == adapter.runtime_instance_id
    assert receipt.runtime_instance_id == adapter.runtime_instance_id
    assert status.receipt == receipt
    assert cancellation.accepted is True
    assert health.runtime_instance_id == adapter.runtime_instance_id
    assert bridge.send_command.await_args_list[1].args == (
        "gamebot_v2_observe",
        observation_request.model_dump(mode="json"),
    )
    assert bridge.send_command.await_args_list[2].args == (
        "gamebot_v2_inspect_region",
        region_request.model_dump(mode="json"),
    )
    assert bridge.send_command.await_args_list[3].kwargs == {"timeout": 12.0}


async def test_adapter_rejects_request_for_another_runtime_before_transport() -> None:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command.return_value = {
        "status": "success",
        "result": GOLDEN["RuntimeManifest"],
    }
    adapter = MinecraftGameBotV2Adapter(bridge)
    await adapter.get_manifest()
    request = ActionInspectionRequest(
        runtime_instance_id="replacement-runtime",
        correlation_id="correlation-1",
    )

    with pytest.raises(GameBotRuntimeError, match="RUNTIME_INSTANCE_CHANGED") as caught:
        await adapter.inspect_action(request)

    assert caught.value.error.outcome_known is False
    assert bridge.send_command.await_count == 1


async def test_adapter_preserves_structured_transport_error() -> None:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command.return_value = {
        "status": "error",
        "result": {
            "code": "UNSUPPORTED_COMMAND",
            "message": "not available",
            "details": {"command": "gamebot_v2_eval_skill"},
        },
    }
    adapter = MinecraftGameBotV2Adapter(bridge)

    with pytest.raises(GameBotRuntimeError) as caught:
        await adapter.get_manifest()

    assert caught.value.error.code == "UNSUPPORTED_COMMAND"
    assert caught.value.error.details == {"command": "gamebot_v2_eval_skill"}
