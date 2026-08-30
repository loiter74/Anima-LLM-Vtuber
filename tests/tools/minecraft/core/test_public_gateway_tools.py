"""The LangChain registry exposes exactly two Minecraft robot capabilities."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
from animetta.tools.minecraft.voyager.journal import CommandDraft, InMemoryCommandJournal
from animetta.tools.minecraft.voyager.public_activity import PublicActivityRecorder
from animetta.tools.minecraft.voyager.sqlite_repository import SQLiteCommandJournal
from animetta.tools.minecraft.voyager.stop import GlobalStopBarrier

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = RuntimeManifest.model_validate(
    json.loads((ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8"))[
        "messages"
    ]["RuntimeManifest"]
)


def test_public_minecraft_surface_is_exactly_two_tools() -> None:
    registered = tools.get_minecraft_tools()

    assert [item.name for item in registered] == ["mc_connection", "mc_operate_bot"]
    assert not hasattr(tools, "mc_execute")
    assert not hasattr(tools, "mc_status")
    assert not hasattr(tools, "mc_stop")
    assert not hasattr(tools, "mc_goto")
    assert not hasattr(tools, "mc_voyager_live")
    assert not hasattr(tools, "_send")


def test_caller_scope_is_not_model_generated_schema() -> None:
    schemas = {
        item.name: item.args_schema.model_json_schema() for item in tools.get_minecraft_tools()
    }

    assert all("caller_scope" not in schema.get("properties", {}) for schema in schemas.values())
    assert "allow_create" not in schemas["mc_connection"].get("properties", {})
    assert set(schemas["mc_connection"]["properties"]["operation"]["enum"]) == {
        "connect",
        "status",
        "disconnect",
        "shutdown",
        "reattach_viewer",
    }
    assert set(schemas["mc_operate_bot"]["properties"]["operation"]["enum"]) == {
        "execute",
        "progress",
        "cancel",
    }
    assert set(schemas["mc_operate_bot"]["properties"]["projection_kind"]["enum"]) == {
        "commands",
        "missions",
        "activities",
    }


def test_execute_schema_rejects_cross_branch_payloads() -> None:
    with pytest.raises(ValueError):
        tools.MinecraftExecuteRequest.model_validate(
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

    with pytest.raises(ValueError, match="execute only accepts"):
        tools.MinecraftOperateToolInput.model_validate(
            {
                "operation": "execute",
                "execute": {
                    "contract_version": "2",
                    "kind": "atomic",
                    "request_id": "request-cross-operation",
                    "action": {"capability": "observe", "parameters": {}},
                },
                "limit": 5,
            }
        )
    with pytest.raises(ValueError, match="cancel only accepts"):
        tools.MinecraftOperateToolInput.model_validate(
            {
                "operation": "cancel",
                "request_id": "cancel-cross-operation",
                "cursor": "unexpected",
            }
        )

    execute = {
        "contract_version": "2",
        "kind": "atomic",
        "request_id": "request-matching-alias",
        "action": {"capability": "observe", "parameters": {}},
    }
    assert (
        tools.MinecraftOperateToolInput.model_validate(
            {
                "operation": "execute",
                "request_id": "request-matching-alias",
                "execute": execute,
            }
        ).request_id
        == "request-matching-alias"
    )
    with pytest.raises(ValueError, match="request_id must match"):
        tools.MinecraftOperateToolInput.model_validate(
            {
                "operation": "execute",
                "request_id": "request-mismatch",
                "execute": execute,
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
        response = await tools.mc_operate_bot.ainvoke({"operation": "execute", "execute": payload})

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

    response = await tools.mc_operate_bot.ainvoke(
        {
            "operation": "execute",
            "execute": {
                "contract_version": "2",
                "kind": "mission",
                "request_id": "construction-public-request",
                "mission": mission.model_dump(mode="json"),
            },
        }
    )

    assert json.loads(response)["mission_id"] == mission.mission_id
    snapshot = await mission_repository.snapshot(mission.mission_id)
    assert snapshot.mission.spec.budget.resource_consumption == (
        mission.budget.resource_consumption
    )


@pytest.mark.asyncio
async def test_execute_and_cancel_require_an_active_connection(monkeypatch) -> None:
    monkeypatch.setattr(tools, "_control_plane", None)

    with pytest.raises(RuntimeError, match="call mc_connection connect first"):
        await tools.mc_operate_bot.ainvoke(
            {
                "operation": "execute",
                "execute": {
                    "contract_version": "2",
                    "kind": "atomic",
                    "request_id": "disconnected-execute",
                    "action": {"capability": "observe", "parameters": {}},
                },
            }
        )
    with pytest.raises(RuntimeError, match="call mc_connection connect first"):
        await tools.mc_operate_bot.ainvoke(
            {"operation": "cancel", "request_id": "disconnected-cancel"}
        )


@pytest.mark.asyncio
async def test_connect_rolls_back_bot_when_control_plane_assembly_fails(monkeypatch) -> None:
    class StubBridge:
        disconnect_request_id: str | None = None

        async def start(self, *, profile, request_id):
            return {"state": "ready", "profile": profile, "request_id": request_id}

        async def disconnect_runtime(self, *, request_id):
            self.disconnect_request_id = request_id
            return {"state": "stopped"}

    async def fail_assembly(*_args, **_kwargs):
        raise RuntimeError("ASSEMBLY_FAILED")

    bridge = StubBridge()
    monkeypatch.setattr(tools, "_bridge", bridge)
    monkeypatch.setattr(tools, "configure_voyager_control_plane", fail_assembly)

    with pytest.raises(RuntimeError, match="ASSEMBLY_FAILED"):
        await tools.manage_minecraft_connection(
            "connect", request_id="connect-failed", profile="managed-local"
        )

    assert bridge.disconnect_request_id == "connect-failed:rollback"


@pytest.mark.asyncio
async def test_public_tool_connect_uses_application_projection_sink(monkeypatch) -> None:
    class StubBridge:
        config = MinecraftConfig(enabled=True)

        async def start(self, *, profile, request_id):
            return {"state": "ready", "profile": profile, "request_id": request_id}

    configured: dict[str, object] = {}

    emitted: list[dict[str, object]] = []

    async def sink(payload: dict[str, object]) -> None:
        emitted.append(payload)

    async def capture_assembly(bridge, *, event_emit=None, **_kwargs):
        configured["bridge"] = bridge
        configured["event_emit"] = event_emit
        return SimpleNamespace()

    bridge = StubBridge()
    monkeypatch.setattr(tools, "_bridge", bridge)
    monkeypatch.setattr(tools, "_event_emit", sink)
    monkeypatch.setattr(tools, "configure_voyager_control_plane", capture_assembly)

    result = await tools.manage_minecraft_connection(
        "connect", request_id="public-tool-connect", profile="external-local"
    )

    assert result["state"] == "ready"
    assert configured == {"bridge": bridge, "event_emit": sink}
    assert emitted == [
        {
            "event": "minecraft.presentation.configured",
            "mode": "off",
            "profile": "external-local",
            "tempo": "normal",
            "seed": "animetta-live-v1",
            "replay_limit": 64,
        }
    ]


@pytest.mark.asyncio
async def test_progress_reads_durable_projection_while_disconnected(
    tmp_path: Path, monkeypatch
) -> None:
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(tmp_path / "journal.sqlite3"),
        skill_path=str(tmp_path / "skills.sqlite3"),
    )
    journal = SQLiteCommandJournal(config.journal_path)
    await journal.connect()
    await journal.create_command(
        CommandDraft(
            command_id="command-offline-1",
            caller_scope="conversation:offline-user",
            request_id="request-offline-1",
            request_hash="a" * 64,
            kind="execute",
            mode="atomic",
            payload={"kind": "atomic"},
            requested_budget={},
            effective_budget={},
            accepted_at_ms=1,
        )
    )
    await journal.close()
    monkeypatch.setattr(tools, "_control_plane", None)
    monkeypatch.setattr(tools, "_bridge", SimpleNamespace(config=config))

    with tools.bind_minecraft_caller_scope("conversation:offline-user"):
        response = await tools.mc_operate_bot.ainvoke(
            {"operation": "progress", "projection_kind": "commands"}
        )

    assert json.loads(response)["commands"][0]["command_id"] == "command-offline-1"


@pytest.mark.asyncio
async def test_activity_progress_replays_public_projection_while_disconnected(
    tmp_path: Path, monkeypatch
) -> None:
    config = MinecraftConfig.model_validate(
        {
            "enabled": True,
            "journal_path": str(tmp_path / "activity-journal.sqlite3"),
            "skill_path": str(tmp_path / "skills.sqlite3"),
            "presentation": {"mode": "full", "replay_limit": 1},
        }
    )
    journal = SQLiteCommandJournal(config.journal_path)
    await journal.connect()
    command = (
        await journal.create_command(
            CommandDraft(
                command_id="private-command-id",
                caller_scope="conversation:offline-user",
                request_id="request-offline-activity",
                request_hash="b" * 64,
                kind="execute",
                mode="mission",
                payload={
                    "mission_id": "public-mission",
                    "goal": {"intent": "build", "target": "minecraft:starter_shelter"},
                },
                requested_budget={},
                effective_budget={},
                accepted_at_ms=1,
            )
        )
    )[0]
    other_command = (
        await journal.create_command(
            CommandDraft(
                command_id="other-private-command-id",
                caller_scope="conversation:other-operator",
                request_id="request-other-activity",
                request_hash="c" * 64,
                kind="execute",
                mode="mission",
                payload={
                    "mission_id": "other-public-mission",
                    "goal": {"intent": "combat", "target": "minecraft:zombie"},
                },
                requested_budget={},
                effective_budget={},
                accepted_at_ms=2,
            )
        )
    )[0]
    times = iter((100, 101, 102))
    recorder = PublicActivityRecorder(
        repository=journal,
        enabled=True,
        now_ms=lambda: next(times),
    )
    await recorder.record_command(command, source_key="planning", phase="planning")
    await recorder.record_command(command, source_key="observing", phase="observing")
    await recorder.record_command(other_command, source_key="other-planning", phase="planning")
    await journal.close()
    monkeypatch.setattr(tools, "_control_plane", None)
    monkeypatch.setattr(tools, "_bridge", SimpleNamespace(config=config))

    with tools.bind_minecraft_caller_scope("conversation:offline-user"):
        first_response = await tools.mc_operate_bot.ainvoke(
            {"operation": "progress", "projection_kind": "activities", "limit": 20}
        )
        first_page = json.loads(first_response)
        second_response = await tools.mc_operate_bot.ainvoke(
            {
                "operation": "progress",
                "projection_kind": "activities",
                "limit": 20,
                "cursor": first_page["next_cursor"],
            }
        )
    global_replay = await tools.read_minecraft_public_activity_replay(limit=20)

    first = first_page["events"][0]
    second = json.loads(second_response)["events"][0]
    assert first["payload"]["phase"] == "planning"
    assert second["payload"]["phase"] == "observing"
    assert first["payload"]["focus"] == {"kind": "structure", "label": "starter shelter"}
    assert first["event"] == "minecraft.activity.projection"
    assert "private-command-id" not in first_response
    assert "conversation:offline-user" not in first_response
    assert len(global_replay.events) == 1
    assert global_replay.events[0].mission_id == "other-public-mission"
    assert global_replay.events[0].payload.intent == "combat"
    global_json = global_replay.model_dump_json()
    assert "conversation:other-operator" not in global_json
    assert "other-private-command-id" not in global_json


async def _noop() -> None:
    return None
