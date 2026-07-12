"""MinecraftBridge adapter and Voyager controller composition."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

from animetta.tools.minecraft.core import tools
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.voyager.contracts import VoyagerMode
from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository


def _adapter_module():
    return importlib.import_module("animetta.tools.minecraft.voyager.adapter")


async def test_adapter_maps_typed_runtime_operations_to_bridge_commands() -> None:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command = AsyncMock(
        side_effect=[
            {
                "status": "success",
                "result": {
                    "protocol_version": "1.0",
                    "runtime_id": "runtime-1",
                    "capabilities": [
                        {"name": "collect", "risk": "survival_safe", "parameters": {}},
                    ],
                },
            },
            {
                "status": "success",
                "result": {
                    "observation_id": "obs-1",
                    "correlation_id": "corr-observe",
                    "runtime_id": "runtime-1",
                    "captured_at": "2026-07-12T00:00:00Z",
                    "inventory": {},
                },
            },
        ]
    )
    adapter = _adapter_module().MinecraftGameBotAdapter(bridge)

    manifest = await adapter.get_capabilities()
    observation = await adapter.observe("corr-observe")

    assert manifest.runtime_id == "runtime-1"
    assert observation.observation_id == "obs-1"
    assert bridge.send_command.await_args_list[0].args == ("capabilities", {})
    assert bridge.send_command.await_args_list[1].args == (
        "observe",
        {"correlation_id": "corr-observe"},
    )


async def test_adapter_fails_on_bridge_error_without_parsing_natural_language() -> None:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command.return_value = {
        "status": "error",
        "result": {"code": "PROTOCOL_UNSUPPORTED", "message": "old runtime"},
    }
    adapter = _adapter_module().MinecraftGameBotAdapter(bridge)

    try:
        await adapter.get_capabilities()
    except RuntimeError as exc:
        assert "PROTOCOL_UNSUPPORTED" in str(exc)
    else:
        raise AssertionError("bridge error must fail adapter operation")


async def test_configure_voyager_controller_composes_all_modes_and_sets_tool_global() -> None:
    class FakeLLM:
        async def chat(self, messages):
            return type("Response", (), {"content": "await collect('oak_log', 1)"})()

    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command = AsyncMock()
    library = SkillLibrary()
    repository = InMemoryVoyagerRepository()

    controller = await tools.configure_voyager_controller(
        bridge,
        llm_service=FakeLLM(),
        library=library,
        repository=repository,
    )
    try:
        status = await controller.status()
        assert status.mode is VoyagerMode.STOPPED
        assert tools._voyager_controller is controller
        assert set(controller._session_factories) == {
            VoyagerMode.LEARN,
            VoyagerMode.LIVE,
            VoyagerMode.FALLBACK,
        }
    finally:
        await controller.stop()
        tools._voyager_controller = None


async def test_fallback_factory_uses_deterministic_survival_runner(monkeypatch) -> None:
    class FakeLLM:
        async def chat(self, messages):
            return type("Response", (), {"content": ""})()

    class FakeReport:
        def summary(self):
            return {"completed": True, "source": "survival_runner"}

    runner = AsyncMock(return_value=FakeReport())

    class FakeRunner:
        def __init__(self, bridge, *, skill_library):
            self.run = runner

    survival_runner = importlib.import_module(
        "animetta.tools.minecraft.survival.runner"
    )
    monkeypatch.setattr(survival_runner, "SurvivalIronRunner", FakeRunner)
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command.return_value = {
        "status": "success",
        "result": {
            "protocol_version": "1.0",
            "runtime_id": "runtime-1",
            "capabilities": [],
        },
    }
    controller = await tools.configure_voyager_controller(
        bridge,
        llm_service=FakeLLM(),
        library=SkillLibrary(),
        repository=InMemoryVoyagerRepository(),
    )
    try:
        await controller.start_fallback()
        result = await controller._session.run_goal(
            "stay safe", reason="no_trusted_skill", parent_task_id="live-1"
        )

        assert result["source"] == "survival_runner"
        assert result["evidence_eligible"] is False
        runner.assert_awaited_once()
    finally:
        await controller.stop()
        tools._voyager_controller = None
        tools._voyager_library = None


async def test_cleanup_stops_controller_library_and_bridge() -> None:
    controller = AsyncMock()
    library = AsyncMock()
    bridge = AsyncMock()
    tools._voyager_controller = controller
    tools._voyager_library = library
    tools._bridge = bridge

    await tools.cleanup_bridge()

    controller.stop.assert_awaited_once()
    library.close_db.assert_awaited_once()
    bridge.stop.assert_awaited_once()
    assert tools._voyager_controller is None
    assert tools._voyager_library is None
    assert tools._bridge is None
