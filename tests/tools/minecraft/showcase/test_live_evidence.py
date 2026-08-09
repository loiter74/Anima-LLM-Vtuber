import json
from types import SimpleNamespace

import pytest
from langchain_core.tools import tool
from pydantic import ValidationError

from animetta.orchestration.graph.tool_observation import (
    ToolInvocation,
    ToolInvocationCompletion,
)
from animetta.services.llm.mock_llm import MockLLM
from animetta.tools.minecraft.core.tools import MinecraftOperateToolInput
from animetta.tools.minecraft.showcase import live as live_module
from animetta.tools.minecraft.showcase.live import (
    _adaptive_acquisition_stage_spans,
    _mission_world_facts,
)
from animetta.tools.minecraft.showcase.scenario import MissionStartBoundary
from tests.tools.minecraft.mission.test_coordinator import _fixed_mission


def test_adaptive_acquisition_partitions_learning_validation_and_reuse() -> None:
    first = SimpleNamespace(accepted_at_ms=100, started_at_ms=110, terminal_at_ms=200)
    second = SimpleNamespace(accepted_at_ms=300, started_at_ms=310, terminal_at_ms=400)

    partition = _adaptive_acquisition_stage_spans(
        [first, second],
        fallback=(10, 20),
    )

    assert partition.discovery_acquisition == (100, 200)
    assert partition.skill_learning_validation == (100, 200)
    assert partition.skill_reuse == (300, 400)
    assert partition.learning_command_count == 1
    assert partition.reuse_command_count == 1


@pytest.mark.asyncio
async def test_mission_world_facts_keep_prior_commits_when_last_command_has_no_record() -> None:
    copper = SimpleNamespace(fact_id="fact:copper")

    class Collector:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def current_world_facts(self, command_id: str) -> tuple[object, ...]:
            self.calls.append(command_id)
            return (copper,) if command_id == "learn-command" else ()

    collector = Collector()

    facts = await _mission_world_facts(
        collector,
        ("learn-command", "failed-reuse-command"),
    )

    assert facts == (copper,)
    assert collector.calls == ["learn-command", "failed-reuse-command"]


async def test_ordinary_conversation_submission_starts_boundary_before_real_tool() -> None:
    """The real graph call is observed, never replaced with a precompiled mission."""

    assert hasattr(live_module, "OrdinaryConversationMissionSubmitter")
    events: list[str] = []
    mission = _fixed_mission().model_copy(update={"mission_id": "ordinary-showcase-001"})

    class Conversation:
        async def process_text(self, **kwargs):
            invocation = ToolInvocation(
                tool_call_id="call-ordinary-001",
                tool_name="mc_operate_bot",
                arguments={
                    "operation": "execute",
                    "execute": {
                        "contract_version": "2",
                        "kind": "mission",
                        "request_id": "request-ordinary-001",
                        "mission": mission.model_dump(mode="json"),
                    },
                },
                session_id="showcase-run-001",
                conversation_id=kwargs["conversation_id"],
            )
            observer = kwargs["tool_invocation_observer"]
            await observer.before_invoke(invocation)
            events.append("real-tool")
            await observer.after_invoke(
                ToolInvocationCompletion(
                    invocation=invocation,
                    result=json.dumps({"mission_id": mission.mission_id}),
                    error=None,
                )
            )
            return {"response_text": "好，我会按真实证据执行。", "error": None}

    def start_mission(mission_id: str) -> MissionStartBoundary:
        events.append("boundary")
        return MissionStartBoundary(
            run_id="showcase-run-001",
            scenario_id="adaptive-showcase-v1",
            scenario_receipt_hash="a" * 64,
            mission_id=mission_id,
            started_at_ms=150,
        )

    clock = iter((100, 200))
    submitter = live_module.OrdinaryConversationMissionSubmitter(
        conversation=Conversation(),
        semantic_validator=lambda _tool_input: {"test_contract": True},
        now_ms=clock.__next__,
    )

    admitted = await submitter.submit_user_text(
        run_id="showcase-run-001",
        user_text="完成复合任务",
        start_mission=start_mission,
    )

    assert events == ["boundary", "real-tool"]
    assert admitted.dialogue.exact_user_text == "完成复合任务"
    assert admitted.dialogue.visible_response == "好，我会按真实证据执行。"
    assert admitted.dialogue.tool_call_id == "call-ordinary-001"
    assert admitted.dialogue.mission_payload == mission
    assert admitted.mission_boundary.mission_id == mission.mission_id


async def test_ordinary_conversation_rejects_multiple_execute_calls_before_mutation() -> None:
    events: list[str] = []
    mission = _fixed_mission().model_copy(update={"mission_id": "ordinary-showcase-002"})

    class Conversation:
        async def process_text(self, **kwargs):
            observer = kwargs["tool_invocation_observer"]
            invocations = tuple(
                ToolInvocation(
                    tool_call_id=f"call-{index}",
                    tool_name="mc_operate_bot",
                    arguments={
                        "operation": "execute",
                        "execute": {
                            "contract_version": "2",
                            "kind": "mission",
                            "request_id": f"request-{index}",
                            "mission": mission.model_dump(mode="json"),
                        },
                    },
                    session_id="showcase-run-002",
                    conversation_id=kwargs["conversation_id"],
                )
                for index in range(2)
            )
            await observer.before_batch(invocations)
            for invocation in invocations:
                await observer.before_invoke(invocation)
                events.append("real-tool")
            return {"response_text": "不应执行", "error": None}

    def start_mission(_mission_id: str) -> MissionStartBoundary:
        events.append("boundary")
        raise AssertionError("boundary must not start for an ambiguous batch")

    submitter = live_module.OrdinaryConversationMissionSubmitter(
        conversation=Conversation(),
        semantic_validator=lambda _tool_input: {"test_contract": True},
    )

    with pytest.raises(RuntimeError, match="SHOWCASE_REQUIRES_EXACTLY_ONE_MC_OPERATE_EXECUTE"):
        await submitter.submit_user_text(
            run_id="showcase-run-002",
            user_text="重复调用不应触发世界变更",
            start_mission=start_mission,
        )

    assert events == []


async def test_ordinary_conversation_rejects_invalid_mission_before_mutation() -> None:
    events: list[str] = []

    class Conversation:
        async def process_text(self, **kwargs):
            observer = kwargs["tool_invocation_observer"]
            invocation = ToolInvocation(
                tool_call_id="call-invalid",
                tool_name="mc_operate_bot",
                arguments={"operation": "execute", "execute": {"kind": "mission"}},
                session_id="showcase-run-invalid",
                conversation_id=kwargs["conversation_id"],
            )
            await observer.before_batch((invocation,))
            await observer.before_invoke(invocation)
            events.append("real-tool")
            return {"response_text": "不应执行", "error": None}

    def start_mission(_mission_id: str) -> MissionStartBoundary:
        events.append("boundary")
        raise AssertionError("invalid input must not cross the mission boundary")

    submitter = live_module.OrdinaryConversationMissionSubmitter(
        conversation=Conversation(),
    )

    with pytest.raises(ValidationError):
        await submitter.submit_user_text(
            run_id="showcase-run-invalid",
            user_text="非法任务不得执行",
            start_mission=start_mission,
        )

    assert events == []


async def test_live_backend_delegates_admission_and_closes_owned_runtime(
    tmp_path, monkeypatch
) -> None:
    mission = _fixed_mission().model_copy(update={"mission_id": "ordinary-showcase-003"})
    boundary = MissionStartBoundary(
        run_id="showcase-run-003",
        scenario_id="adaptive-showcase-v1",
        scenario_receipt_hash="b" * 64,
        mission_id=mission.mission_id,
        started_at_ms=300,
    )

    class Bridge:
        is_running = True

        def __init__(self) -> None:
            self.stop_calls = 0

        def set_viewer_callback(self, _callback) -> None:
            return None

        async def shutdown_runtime(self, *, request_id: str) -> None:
            del request_id
            self.stop_calls += 1

    class Submitter:
        def __init__(self) -> None:
            self.calls = []
            self.closed = False

        async def submit_user_text(self, **kwargs):
            self.calls.append(kwargs)
            returned_boundary = kwargs["start_mission"](mission.mission_id)
            return live_module.AdmittedDialogue(
                dialogue=live_module.DialogueSubmission(
                    exact_user_text=kwargs["user_text"],
                    visible_response="收到，开始执行。",
                    tool_name="mc_operate_bot",
                    tool_call_id="call-003",
                    mission_id=mission.mission_id,
                    mission_payload=mission,
                    started_at_ms=100,
                    finished_at_ms=200,
                ),
                mission_boundary=returned_boundary,
            )

        async def close(self) -> None:
            self.closed = True

    class Narrator:
        def __init__(self) -> None:
            self.closed = False

        async def narrate(self, _evidence):
            return "仅基于证据的总结"

        async def close(self) -> None:
            self.closed = True

    cleanup_calls = 0

    async def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    monkeypatch.setattr(live_module, "cleanup_bridge", cleanup)
    bridge = Bridge()
    submitter = Submitter()
    narrator = Narrator()
    backend = live_module.LiveShowcaseBackend(
        bridge=bridge,
        submitter=submitter,
        narrator=narrator,
        capture_probe_path=tmp_path / "probe.png",
    )

    admitted = await backend.submit_user_text(
        run_id="showcase-run-003",
        user_text="真实普通会话",
        start_mission=lambda _mission_id: boundary,
    )
    await backend.close()

    assert admitted.mission_boundary == boundary
    assert submitter.calls[0]["user_text"] == "真实普通会话"
    assert submitter.closed is True
    assert narrator.closed is True
    assert cleanup_calls == 1
    assert bridge.stop_calls == 1


async def test_create_submitter_reuses_public_tools_in_ordinary_orchestrator(
    monkeypatch,
) -> None:
    public_tools = [object(), object()]
    conversation = SimpleNamespace(stop=lambda: None)
    calls: dict[str, object] = {}

    class Manager:
        def __init__(self, session_id, service_context) -> None:
            calls["manager_session_id"] = session_id
            calls["service_context"] = service_context

        async def load_prebuilt_tools(self, tools) -> bool:
            calls["tools"] = tools
            return True

    class Orchestrator:
        @classmethod
        async def create(cls, **kwargs):
            calls["orchestrator"] = kwargs
            return conversation

    monkeypatch.setattr(live_module, "ToolManager", Manager, raising=False)
    monkeypatch.setattr(
        live_module,
        "LangGraphOrchestrator",
        Orchestrator,
        raising=False,
    )
    monkeypatch.setattr(live_module, "get_minecraft_tools", lambda: public_tools)

    submitter = await live_module.create_ordinary_showcase_submitter(
        llm=object(),
        socketio=object(),
    )

    assert isinstance(submitter, live_module.OrdinaryConversationMissionSubmitter)
    assert calls["tools"] is public_tools
    orchestrator_args = calls["orchestrator"]
    assert orchestrator_args["service_context"] is calls["service_context"]
    assert orchestrator_args["socketio"] is not None
    assert orchestrator_args["enable_tools"] is True
    assert orchestrator_args["enable_memory"] is False
    assert orchestrator_args["tool_manager"].__class__ is Manager


async def test_full_ordinary_graph_admits_the_observed_public_tool_call(
    monkeypatch,
) -> None:
    mission = _fixed_mission().model_copy(update={"mission_id": "ordinary-showcase-004"})
    events: list[str] = []

    @tool("mc_operate_bot", args_schema=MinecraftOperateToolInput)
    async def fake_mc_operate_bot(**_kwargs) -> str:
        """Submit one typed test mission."""

        events.append("real-tool")
        return json.dumps({"mission_id": mission.mission_id})

    @tool("mc_connection")
    async def fake_mc_connection(operation: str, request_id: str) -> str:
        """Manage the test runtime connection."""

        del operation, request_id

        return "{}"

    class ScriptedLLM(MockLLM):
        def __init__(self) -> None:
            super().__init__()
            self.tool_turns = 0

        async def chat_with_tools(self, _prompt, **_kwargs):
            self.tool_turns += 1
            if self.tool_turns == 1:
                return {
                    "content": "收到，我会先提交有边界的任务。",
                    "tool_calls": [
                        {
                            "id": "call-full-graph-004",
                            "name": "mc_operate_bot",
                            "args": {
                                "operation": "execute",
                                "execute": {
                                    "contract_version": "2",
                                    "kind": "mission",
                                    "request_id": "request-full-graph-004",
                                    "mission": mission.model_dump(mode="json"),
                                },
                            },
                        }
                    ],
                }
            return {"content": "任务已经通过普通会话提交。", "tool_calls": []}

    monkeypatch.setattr(
        live_module,
        "get_minecraft_tools",
        lambda: [fake_mc_connection, fake_mc_operate_bot],
    )
    submitter = await live_module.create_ordinary_showcase_submitter(
        llm=ScriptedLLM(),
        semantic_validator=lambda _tool_input: {"full_graph_contract": True},
    )

    def start_mission(mission_id: str) -> MissionStartBoundary:
        events.append("boundary")
        return MissionStartBoundary(
            run_id="showcase-run-004",
            scenario_id="adaptive-showcase-v1",
            scenario_receipt_hash="c" * 64,
            mission_id=mission_id,
            started_at_ms=400,
        )

    try:
        admitted = await submitter.submit_user_text(
            run_id="showcase-run-004",
            user_text="从普通会话完成复合任务",
            start_mission=start_mission,
        )
    finally:
        await submitter.close()

    assert events == ["boundary", "real-tool"]
    assert admitted.dialogue.tool_call_id == "call-full-graph-004"
    assert admitted.dialogue.visible_response == "任务已经通过普通会话提交。"
    assert admitted.dialogue.mission_payload == mission
