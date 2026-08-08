from __future__ import annotations

import json

from animetta.orchestration.graph.state import create_initial_state
from animetta.orchestration.graph.tool_node import tool_node
from animetta.orchestration.prompting.pipeline import compile as compile_prompt
from animetta.tools.minecraft.core.tools import MinecraftExecuteToolInput, get_minecraft_tools
from tests.tools.minecraft.mission.test_coordinator import _fixed_mission


async def test_compiled_prompt_routes_fixed_and_compound_requests_to_typed_missions() -> None:
    state = create_initial_state(
        "session-minecraft-dialogue",
        user_text="先打三种怪，再独立造房并探索一个新物品、学会可复用技能和解锁两个成就",
        system_prompt="You are Anima.",
    )
    tools = get_minecraft_tools()
    compiled = await compile_prompt(
        state,
        {"configurable": {"tools_map": {item.name: item for item in tools}}},
    )

    assert "Minecraft typed mission contract" in compiled.system_prompt
    assert "contract_version=2" in compiled.system_prompt
    assert "Never select learn, live, or fallback" in compiled.system_prompt
    assert "never use the atomic branch for an ordinary user request" in compiled.system_prompt
    assert "each combat goal actions=4, attempts=2" in compiled.system_prompt
    assert "shelter actions=84" in compiled.system_prompt
    assert "blocks=85" in compiled.system_prompt
    assert "minecraft_mission" in compiled.section_names

    fixed = _fixed_mission().model_copy(update={"objectives": (_fixed_mission().objectives[0],)})
    fixed_input = MinecraftExecuteToolInput.model_validate(
        {
            "contract_version": "2",
            "kind": "mission",
            "request_id": "dialogue-fixed-1",
            "mission": fixed.model_dump(mode="json"),
        }
    )
    compound_input = MinecraftExecuteToolInput.model_validate(
        {
            "contract_version": "2",
            "kind": "mission",
            "request_id": "dialogue-compound-1",
            "mission": _fixed_mission().model_dump(mode="json"),
        }
    )

    assert fixed_input.request.kind == "mission"
    assert len(fixed_input.request.mission.objectives) == 1
    assert compound_input.request.kind == "mission"
    assert len(compound_input.request.mission.objectives) == 2


async def test_invalid_mission_gets_one_repair_then_execution_is_blocked() -> None:
    from animetta.tools.minecraft.core.tools import mc_execute

    invalid_call = {
        "id": "call-invalid-1",
        "name": "mc_execute",
        "args": {
            "contract_version": "2",
            "kind": "mission",
            "request_id": "dialogue-invalid-1",
            "mission": {"schema_version": "1", "objectives": []},
        },
    }
    state = create_initial_state("session-repair", user_text="去完成任务")
    state["tool_calls"] = [invalid_call]
    config = {"configurable": {"tools_map": {"mc_execute": mc_execute}}}

    first = await tool_node(state, config)
    first_problem = json.loads(first["messages"][0].content)
    assert first_problem["error"]["code"] == "MC_MISSION_SCHEMA_INVALID"
    assert first_problem["error"]["repair_remaining"] is True

    state["messages"] = first["messages"]
    state["tool_calls"] = [{**invalid_call, "id": "call-invalid-2"}]
    second = await tool_node(state, config)
    second_problem = json.loads(second["messages"][0].content)
    assert second_problem["error"]["repair_remaining"] is False

    class MustNotRun:
        calls = 0

        async def ainvoke(self, _args):
            self.calls += 1
            raise AssertionError("third mission attempt executed")

    blocked_tool = MustNotRun()
    state["messages"] = [*first["messages"], *second["messages"]]
    state["tool_calls"] = [{**invalid_call, "id": "call-invalid-3"}]
    third = await tool_node(
        state,
        {"configurable": {"tools_map": {"mc_execute": blocked_tool}}},
    )

    assert blocked_tool.calls == 0
    assert json.loads(third["messages"][0].content)["error"]["code"] == (
        "MC_MISSION_REPAIR_EXHAUSTED"
    )


async def test_final_narration_instruction_requires_committed_status_evidence() -> None:
    state = create_initial_state("session-summary", user_text="现在完成了吗？")
    compiled = await compile_prompt(
        state,
        {"configurable": {"tools_map": {item.name: item for item in get_minecraft_tools()}}},
    )

    assert "Call mc_status" in compiled.system_prompt
    assert "Never claim an objective, discovery, skill, or advancement" in (compiled.system_prompt)


async def test_tool_node_injects_conversation_scope_for_minecraft_tools() -> None:
    from animetta.tools.minecraft.core import tools as mc_tools

    class ScopedStatus:
        async def ainvoke(self, _args):
            return mc_tools._caller_scope.get()

    state = create_initial_state(
        "session-scope",
        conversation_id="conversation-001",
    )
    state["tool_calls"] = [{"id": "status-1", "name": "mc_status", "args": {}}]

    result = await tool_node(
        state,
        {"configurable": {"tools_map": {"mc_status": ScopedStatus()}}},
    )

    assert result["tool_results"][0]["result"] == "conversation:conversation-001"
