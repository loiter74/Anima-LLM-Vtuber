"""The LangChain registry exposes exactly the three unified Minecraft tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from animetta.tools.gamebot.contracts.v2 import RuntimeManifest
from animetta.tools.minecraft.core import tools
from animetta.tools.minecraft.core.assembly import _budget_policy
from animetta.tools.minecraft.core.config import MinecraftConfig
from animetta.tools.minecraft.mission.coordinator import MissionCoordinator
from animetta.tools.minecraft.mission.projection import MissionProjectionService
from animetta.tools.minecraft.mission.repository import InMemoryMissionRepository
from animetta.tools.minecraft.showcase.micro_gates import build_construction_mission
from animetta.tools.minecraft.voyager.gateway import CommandHandle, VoyagerGateway
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal
from animetta.tools.minecraft.voyager.stop import GlobalStopBarrier

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = RuntimeManifest.model_validate(
    json.loads((ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8"))[
        "messages"
    ]["RuntimeManifest"]
)


def test_public_minecraft_surface_is_exactly_three_tools() -> None:
    registered = tools.get_minecraft_tools()

    assert [item.name for item in registered] == ["mc_execute", "mc_status", "mc_stop"]
    assert not hasattr(tools, "mc_goto")
    assert not hasattr(tools, "mc_voyager_live")
    assert not hasattr(tools, "_send")


def test_caller_scope_is_not_model_generated_schema() -> None:
    schemas = {
        item.name: item.args_schema.model_json_schema() for item in tools.get_minecraft_tools()
    }

    assert all("caller_scope" not in schema.get("properties", {}) for schema in schemas.values())
    execute_schema = schemas["mc_execute"]
    assert execute_schema["type"] == "object"
    assert execute_schema["discriminator"]["propertyName"] == "kind"
    assert set(execute_schema["discriminator"]["mapping"]) == {"mission", "atomic"}
    assert "request" not in execute_schema.get("properties", {})


def test_execute_schema_rejects_cross_branch_payloads() -> None:
    with pytest.raises(ValueError):
        tools.MinecraftExecuteToolInput.model_validate(
            {
                "contract_version": "2",
                "kind": "atomic",
                "request_id": "request-cross-branch",
                "action": {"capability": "collect", "parameters": {"count": 1}},
                "mission": {
                    "mission_id": "must-not-be-accepted",
                    "objectives": [],
                    "budget": {},
                },
            }
        )


@pytest.mark.asyncio
async def test_execute_injects_caller_scope_outside_model_arguments(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class StubGateway:
        async def execute(self, *, caller_scope, request):
            captured.update(caller_scope=caller_scope, request=request)
            return CommandHandle(
                command_id="command-1",
                request_id=request.request_id,
                queue_sequence=1,
                state="queued",
                accepted_at_ms=1,
                idempotency_reused=False,
                projection_version=1,
            )

    monkeypatch.setattr(tools, "_gateway", lambda: StubGateway())
    payload = {
        "contract_version": "2",
        "kind": "atomic",
        "request_id": "request-1",
        "action": {"capability": "collect", "parameters": {"count": 1}},
    }

    with tools.bind_minecraft_caller_scope("conversation:user-001"):
        response = await tools.mc_execute.ainvoke(payload)

    assert captured["caller_scope"] == "conversation:user-001"
    assert "caller_scope" not in captured["request"].model_dump(mode="json")
    assert json.loads(response)["command_id"] == "command-1"


@pytest.mark.asyncio
async def test_public_execute_admits_construction_with_its_finite_material_budget(
    monkeypatch,
) -> None:
    command_repository = InMemoryCommandJournal()
    mission_repository = InMemoryMissionRepository()
    coordinator = MissionCoordinator(
        repository=mission_repository,
        journal=command_repository,
    )
    projection = MissionProjectionService(
        repository=mission_repository,
        journal=command_repository,
    )
    gateway = VoyagerGateway(
        repository=command_repository,
        stop_barrier=GlobalStopBarrier(
            repository=command_repository,
            signal_active=lambda _command_id: _noop(),
            now_ms=lambda: 100,
        ),
        manifest=MANIFEST,
        budget_policy=_budget_policy(MinecraftConfig()),
        now_ms=lambda: 100,
        make_id=lambda prefix: f"{prefix}-1",
        mission_coordinator=coordinator,
        mission_projection=projection,
    )
    monkeypatch.setattr(tools, "_gateway", lambda: gateway)
    mission = build_construction_mission(mission_id="construction-public-path")

    response = await tools.mc_execute.ainvoke(
        {
            "contract_version": "2",
            "kind": "mission",
            "request_id": "construction-public-request",
            "mission": mission.model_dump(mode="json"),
        }
    )

    assert json.loads(response)["mission_id"] == mission.mission_id
    snapshot = await mission_repository.snapshot(mission.mission_id)
    assert snapshot.mission.spec.budget.resource_consumption == (
        mission.budget.resource_consumption
    )


async def _noop() -> None:
    return None
