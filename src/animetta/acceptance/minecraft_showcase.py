"""Whole-application adapters for the real adaptive Minecraft acceptance showcase."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from PIL import ImageGrab

from animetta.config.providers.llm.deepseek import DeepSeekLLMConfig
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator
from animetta.orchestration.graph.state import create_initial_state
from animetta.orchestration.graph.tool_manager import ToolManager
from animetta.orchestration.graph.tool_observation import (
    ToolInvocation,
    ToolInvocationCompletion,
    ToolInvocationObserver,
)
from animetta.orchestration.prompting.pipeline import compile as compile_prompt
from animetta.runtime.session_context import ServiceContext
from animetta.services.llm.interface import LLMInterface
from animetta.services.llm.openai_llm import OpenAILLM
from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    starter_shelter_blueprint,
)
from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
from animetta.tools.minecraft.core.tools import (
    MinecraftExecuteRequest,
    MinecraftOperateToolInput,
    bind_minecraft_caller_scope,
    cleanup_bridge,
    configure_voyager_control_plane,
    get_minecraft_tools,
    mc_operate_bot,
)
from animetta.tools.minecraft.mission.adaptive import ExplorationFrontier
from animetta.tools.minecraft.mission.models import (
    CheckpointIO,
    MissionReport,
    NovelFactsAcquiredAtLeast,
    StageFailure,
    TrustedSkillsCreatedAtLeast,
    VanillaAdvancementsAddedAtLeast,
    VerificationPredicate,
)
from animetta.tools.minecraft.mission.repository import MissionStatus
from animetta.tools.minecraft.showcase.runner import (
    AdmittedDialogue,
    CapturedMedia,
    DialogueSubmission,
    MediaCaptureBundle,
    ShowcaseEvidenceSnapshot,
    StageEvidence,
    ViewerReadiness,
)
from animetta.tools.minecraft.showcase.scenario import (
    MissionStartBoundary,
    ScenarioSpec,
    SetupExecutionResult,
    SetupOperation,
    render_rcon_command,
)
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint
from animetta.tools.minecraft.voyager.goal_models import (
    BuildGoal,
    CombatGoal,
    EntityDefeated,
    StructureMatchesBlueprint,
)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _showcase_conversation_ids(run_id: str) -> tuple[str, str, str]:
    namespace = f"animetta-showcase:{run_id}"
    return (
        str(uuid5(NAMESPACE_URL, f"{namespace}:message")),
        str(uuid5(NAMESPACE_URL, f"{namespace}:conversation")),
        str(uuid5(NAMESPACE_URL, f"{namespace}:task")),
    )


def _normalize_model_execute_args(args: object) -> object:
    """Recover only the unambiguous natural-language mission branch.

    Some OpenAI-compatible providers omit a required discriminator even when
    they emit the complete ``mission`` object.  Keep the public tool contract
    strict and repair only this one provider-boundary shape; atomic or
    ambiguous payloads still fail normal validation.
    """

    if not isinstance(args, dict):
        return args
    execute = args.get("execute")
    if (
        args.get("operation") == "execute"
        and isinstance(execute, dict)
        and "kind" not in execute
        and isinstance(execute.get("mission"), dict)
        and execute.get("action") is None
    ):
        return {**args, "execute": {**execute, "kind": "mission"}}
    return args


def _added_advancement_ids(events: tuple[Any, ...]) -> list[str]:
    """Project the GameBot v2 ``add`` action into the final narration input."""

    return [event.advancement_id for event in events if event.action == "add"]


@dataclass(frozen=True, slots=True)
class _AdaptiveAcquisitionStageSpans:
    discovery_acquisition: tuple[int, int]
    skill_learning_validation: tuple[int, int]
    skill_reuse: tuple[int, int]
    learning_command_count: int
    reuse_command_count: int


def _command_span(commands: list[Any], fallback: tuple[int, int]) -> tuple[int, int]:
    if not commands:
        return fallback
    starts = [item.accepted_at_ms for item in commands]
    finishes = [
        item.terminal_at_ms or item.started_at_ms or item.accepted_at_ms for item in commands
    ]
    return min(starts), max(finishes)


def _adaptive_acquisition_stage_spans(
    commands: list[Any], *, fallback: tuple[int, int]
) -> _AdaptiveAcquisitionStageSpans:
    """Map source-A/B learning and source-C reuse onto two commands."""

    learning_commands = commands[:1]
    reuse_commands = commands[1:]
    learning_span = _command_span(learning_commands, fallback)
    return _AdaptiveAcquisitionStageSpans(
        discovery_acquisition=learning_span,
        skill_learning_validation=learning_span,
        skill_reuse=_command_span(reuse_commands, learning_span),
        learning_command_count=len(learning_commands),
        reuse_command_count=len(reuse_commands),
    )


def _selected_strategy(command: Any) -> str | None:
    terminal = command.terminal_result
    if not isinstance(terminal, dict):
        return None
    output = terminal.get("output")
    if not isinstance(output, dict):
        return None
    selected = output.get("selected_strategy")
    return selected if isinstance(selected, str) else None


async def _mission_advancement_events(
    evidence_collector: Any,
    command_ids: tuple[str, ...],
) -> tuple[Any, ...]:
    """Keep scoped advancement evidence when the final command has no record."""

    events_by_hash: dict[str, Any] = {}
    for command_id in command_ids:
        events = await evidence_collector.current_advancement_events(command_id)
        for event in events:
            events_by_hash.setdefault(event.content_hash, event)
    return tuple(
        sorted(
            events_by_hash.values(),
            key=lambda event: (event.observed_at_ms, event.content_hash),
        )
    )


async def _mission_world_facts(
    evidence_collector: Any,
    command_ids: tuple[str, ...],
) -> tuple[Any, ...]:
    """Keep committed mission facts when a later failed command has no record."""

    facts_by_id: dict[str, Any] = {}
    for command_id in command_ids:
        facts = await evidence_collector.current_world_facts(command_id)
        for fact in facts:
            facts_by_id[fact.fact_id] = fact
    return tuple(facts_by_id[fact_id] for fact_id in sorted(facts_by_id))


def _semantic_assertions(validated: MinecraftExecuteRequest) -> dict[str, bool]:
    request = validated.request
    if request.kind != "mission":
        return {"mission_branch": False}
    mission = request.mission
    combats = [
        objective for objective in mission.objectives if isinstance(objective.goal, CombatGoal)
    ]
    defeated = {
        predicate.entity
        for objective in combats
        for predicate in objective.goal.success_predicates
        if isinstance(predicate, EntityDefeated)
    }
    builds = [
        objective for objective in mission.objectives if isinstance(objective.goal, BuildGoal)
    ]
    shelter_cost = (
        BlueprintCompiler()
        .compile(
            starter_shelter_blueprint(),
            BlueprintBinding(origin=(0, 0, 0), materials={}),
        )
        .static_cost
    )
    shelter = next(
        (
            objective
            for objective in builds
            if any(
                isinstance(predicate, StructureMatchesBlueprint)
                and predicate.blueprint_id == "starter-shelter-v1"
                for predicate in objective.goal.success_predicates
            )
        ),
        None,
    )
    completion = mission.completion_predicates
    return {
        "mission_branch": True,
        "three_monsters": {
            "minecraft:zombie",
            "minecraft:skeleton",
            "minecraft:spider",
        }.issubset(defeated),
        "combat_navigation_budget": len(combats) >= 3
        and all(
            item.budget.max_actions >= 2 and item.budget.max_strategy_attempts >= 2
            for item in combats
        ),
        "starter_shelter": shelter is not None,
        "shelter_budget": shelter is not None
        and shelter.budget.max_actions >= shelter_cost.max_actions
        and shelter.budget.max_blocks_changed >= shelter_cost.max_blocks_changed,
        "bounded_autonomy": mission.autonomy.mode == "bounded"
        and {"discovery", "skill"}.issubset(mission.autonomy.allowed_domains),
        "skill_learning": mission.execution.allow_skill_learning,
        "novel_item": any(
            isinstance(item, NovelFactsAcquiredAtLeast) and item.count >= 1 for item in completion
        ),
        "trusted_skill": any(
            isinstance(item, TrustedSkillsCreatedAtLeast) and item.count >= 1 for item in completion
        ),
        "advancements": any(
            isinstance(item, VanillaAdvancementsAddedAtLeast) and item.count >= 2
            for item in completion
        ),
    }


@dataclass(frozen=True, slots=True)
class InterpretedMission:
    dialogue: DialogueSubmission
    tool_input: MinecraftExecuteRequest
    validation: dict[str, bool]


def configured_showcase_llm_from_environment() -> OpenAILLM:
    load_dotenv(Path(".env"), override=False)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is unavailable")
    return OpenAILLM.from_config(
        DeepSeekLLMConfig(
            api_key=api_key,
            model="deepseek-v4-flash",
            thinking="disabled",
            temperature=0.2,
            top_p=0.9,
            max_tokens=16_000,
        )
    )


class ConfiguredModelEvidenceNarrator:
    """Narrate only committed evidence after ordinary conversation admission."""

    def __init__(self, llm: OpenAILLM) -> None:
        self._llm = llm

    async def narrate(self, evidence: dict[str, Any]) -> str:
        return await self._llm.chat(
            "请以 Anima 的口吻简洁总结本次 Minecraft 任务。只能陈述下面 progress 与已提交证据中"
            "明确存在的结果；失败或缺失必须直说。\n"
            + json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            system_prompt="You are Anima. Never claim gameplay without committed evidence.",
            max_tokens=800,
        )

    async def close(self) -> None:
        await self._llm.close()


class ConfiguredModelMissionInterpreter(ConfiguredModelEvidenceNarrator):
    """R6 contract probe; final R8 uses the ordinary LangGraph conversation."""

    @classmethod
    def from_environment(cls) -> ConfiguredModelMissionInterpreter:
        return cls(configured_showcase_llm_from_environment())

    async def interpret(self, *, run_id: str, user_text: str) -> InterpretedMission:
        tools = get_minecraft_tools()
        state = create_initial_state(
            f"showcase-dialogue:{run_id}",
            user_text=user_text,
            system_prompt="You are Anima. Acknowledge briefly and use tools precisely.",
        )
        compiled = await compile_prompt(
            state,
            {"configurable": {"tools_map": {item.name: item for item in tools}}},
        )
        history: list[Any] = []
        error = ""
        started_at_ms = _now_ms()
        for attempt in range(1, 3):
            prompt = (
                user_text
                if attempt == 1
                else (
                    "修复上一条 mc_operate_bot execute 调用，重新输出完整 mission；校验错误："
                    + error
                )
            )
            response = await self._llm.chat_with_tools(
                prompt,
                tools=tools,
                langchain_history=history,
                system_prompt=compiled.system_prompt,
            )
            calls = [
                call
                for call in response.get("tool_calls") or []
                if call.get("name") == "mc_operate_bot"
            ]
            validated: MinecraftExecuteRequest | None = None
            semantics: dict[str, bool] = {}
            if len(calls) == 1:
                try:
                    operate = MinecraftOperateToolInput.model_validate(
                        _normalize_model_execute_args(calls[0].get("args", {}))
                    )
                    if operate.operation != "execute" or operate.execute is None:
                        raise ValueError("expected mc_operate_bot execute")
                    validated = operate.execute
                    semantics = _semantic_assertions(validated)
                    if not all(semantics.values()):
                        error = "semantic assertions failed: " + json.dumps(
                            semantics, ensure_ascii=False, sort_keys=True
                        )
                        validated = None
                except Exception as exc:
                    error = str(exc)
            else:
                error = "expected exactly one mc_operate_bot execute call"
            if validated is not None and validated.request.kind == "mission":
                call = calls[0]
                mission = validated.request.mission
                return InterpretedMission(
                    dialogue=DialogueSubmission(
                        exact_user_text=user_text,
                        visible_response=str(response.get("content", "")),
                        tool_name="mc_operate_bot",
                        tool_call_id=str(call.get("id", "model-tool-call")),
                        mission_id=mission.mission_id,
                        mission_payload=mission,
                        started_at_ms=started_at_ms,
                        finished_at_ms=_now_ms(),
                    ),
                    tool_input=validated,
                    validation=semantics,
                )
            response_calls = response.get("tool_calls") or []
            history.extend(
                [
                    HumanMessage(content=prompt),
                    AIMessage(
                        content=str(response.get("content", "")),
                        tool_calls=response_calls,
                    ),
                    *(
                        ToolMessage(
                            content=json.dumps(
                                {"ok": False, "error": error},
                                ensure_ascii=False,
                            ),
                            tool_call_id=str(call.get("id", "")),
                        )
                        for call in response_calls
                    ),
                ]
            )
        raise RuntimeError(f"REAL_MODEL_MISSION_INVALID:{error}")


class OrdinaryConversationPort(Protocol):
    """The same process_text boundary used by normal Anima chat handling."""

    async def process_text(
        self,
        *,
        text: str,
        message_id: str,
        conversation_id: str,
        task_id: str,
        tool_invocation_observer: ToolInvocationObserver,
    ) -> dict[str, Any]: ...

    async def stop(self) -> None: ...


class MissionSubmitter(Protocol):
    async def submit_user_text(
        self,
        *,
        run_id: str,
        user_text: str,
        start_mission: Callable[[str], MissionStartBoundary],
    ) -> AdmittedDialogue: ...

    async def close(self) -> None: ...


class EvidenceNarrator(Protocol):
    async def narrate(self, evidence: dict[str, Any]) -> str: ...

    async def close(self) -> None: ...


class _MissionInvocationObserver:
    def __init__(
        self,
        *,
        start_mission: Callable[[str], MissionStartBoundary],
        semantic_validator: Callable[[MinecraftExecuteRequest], dict[str, bool]],
    ) -> None:
        self._start_mission = start_mission
        self._semantic_validator = semantic_validator
        self.attempt_count = 0
        self.invocation: ToolInvocation | None = None
        self.tool_input: MinecraftExecuteRequest | None = None
        self.validation: dict[str, bool] = {}
        self.boundary: MissionStartBoundary | None = None
        self.completion: ToolInvocationCompletion | None = None

    async def before_batch(self, invocations: tuple[ToolInvocation, ...]) -> None:
        mission_calls = tuple(
            invocation
            for invocation in invocations
            if invocation.tool_name == "mc_operate_bot"
            and invocation.arguments.get("operation") == "execute"
        )
        if len(mission_calls) != 1:
            raise RuntimeError("SHOWCASE_REQUIRES_EXACTLY_ONE_MC_OPERATE_EXECUTE")

    async def before_invoke(self, invocation: ToolInvocation) -> None:
        if (
            invocation.tool_name != "mc_operate_bot"
            or invocation.arguments.get("operation") != "execute"
        ):
            return
        self.attempt_count += 1
        if self.attempt_count != 1:
            raise RuntimeError("SHOWCASE_REQUIRES_EXACTLY_ONE_MC_OPERATE_EXECUTE")
        operate = MinecraftOperateToolInput.model_validate(invocation.arguments)
        if operate.execute is None:
            raise RuntimeError("SHOWCASE_REQUIRES_MISSION_BRANCH")
        validated = operate.execute
        if validated.request.kind != "mission":
            raise RuntimeError("SHOWCASE_REQUIRES_MISSION_BRANCH")
        validation = self._semantic_validator(validated)
        if not validation or not all(validation.values()):
            raise RuntimeError(
                "SHOWCASE_MISSION_SEMANTICS_INVALID:"
                + json.dumps(validation, ensure_ascii=False, sort_keys=True)
            )
        mission = validated.request.mission
        self.invocation = invocation
        self.tool_input = validated
        self.validation = validation
        self.boundary = self._start_mission(mission.mission_id)

    async def after_invoke(self, completion: ToolInvocationCompletion) -> None:
        if (
            completion.invocation.tool_name == "mc_operate_bot"
            and completion.invocation.arguments.get("operation") == "execute"
        ):
            self.completion = completion


class OrdinaryConversationMissionSubmitter:
    """Observe one ordinary graph turn and retain its real bot execute call."""

    def __init__(
        self,
        *,
        conversation: OrdinaryConversationPort,
        semantic_validator: Callable[[MinecraftExecuteRequest], dict[str, bool]] = (
            _semantic_assertions
        ),
        now_ms: Callable[[], int] = _now_ms,
    ) -> None:
        self._conversation = conversation
        self._semantic_validator = semantic_validator
        self._now_ms = now_ms

    async def submit_user_text(
        self,
        *,
        run_id: str,
        user_text: str,
        start_mission: Callable[[str], MissionStartBoundary],
    ) -> AdmittedDialogue:
        started_at_ms = self._now_ms()
        observer = _MissionInvocationObserver(
            start_mission=start_mission,
            semantic_validator=self._semantic_validator,
        )
        message_id, conversation_id, task_id = _showcase_conversation_ids(run_id)
        result = await self._conversation.process_text(
            text=user_text,
            message_id=message_id,
            conversation_id=conversation_id,
            task_id=task_id,
            tool_invocation_observer=observer,
        )
        finished_at_ms = self._now_ms()
        if result.get("error"):
            raise RuntimeError(f"SHOWCASE_CONVERSATION_FAILED:{result['error']}")
        if observer.attempt_count != 1:
            raise RuntimeError("SHOWCASE_REQUIRES_EXACTLY_ONE_MC_OPERATE_EXECUTE")
        if (
            observer.invocation is None
            or observer.tool_input is None
            or observer.boundary is None
            or observer.completion is None
        ):
            raise RuntimeError("SHOWCASE_MC_OPERATE_EXECUTE_NOT_COMPLETED")
        if observer.completion.error is not None:
            raise RuntimeError(f"SHOWCASE_MC_OPERATE_EXECUTE_FAILED:{observer.completion.error}")
        raw_handle = observer.completion.result
        handle = json.loads(raw_handle) if isinstance(raw_handle, str) else raw_handle
        mission = observer.tool_input.request.mission
        if not isinstance(handle, dict) or handle.get("mission_id") != mission.mission_id:
            raise RuntimeError("MISSION_HANDLE_IDENTITY_MISMATCH")
        visible_response = str(result.get("response_text", "")).strip()
        if not visible_response:
            raise RuntimeError("SHOWCASE_VISIBLE_ACKNOWLEDGEMENT_MISSING")
        return AdmittedDialogue(
            dialogue=DialogueSubmission(
                exact_user_text=user_text,
                visible_response=visible_response,
                tool_name="mc_operate_bot",
                tool_call_id=observer.invocation.tool_call_id,
                mission_id=mission.mission_id,
                mission_payload=mission,
                started_at_ms=started_at_ms,
                finished_at_ms=finished_at_ms,
            ),
            mission_boundary=observer.boundary,
        )

    async def close(self) -> None:
        await self._conversation.stop()


class _DiscardingSocketIO:
    """Keep the ordinary output node intact when no frontend relay is requested."""

    async def emit(self, _event: str, _payload: object, **_kwargs: object) -> None:
        return None


async def create_ordinary_showcase_submitter(
    *,
    llm: LLMInterface,
    socketio: Any | None = None,
    semantic_validator: Callable[[MinecraftExecuteRequest], dict[str, bool]] = (
        _semantic_assertions
    ),
) -> OrdinaryConversationMissionSubmitter:
    """Build the normal LangGraph conversation over runtime-owned public tools."""

    session_id = "minecraft-adaptive-showcase"
    service_context = ServiceContext()
    service_context.session_id = session_id
    service_context.llm_engine = llm
    tool_manager = ToolManager(session_id, service_context)
    tools = get_minecraft_tools()
    if not await tool_manager.load_prebuilt_tools(tools):
        raise RuntimeError("SHOWCASE_PUBLIC_TOOL_BINDING_FAILED")
    conversation = await LangGraphOrchestrator.create(
        session_id=session_id,
        service_context=service_context,
        socketio=socketio or _DiscardingSocketIO(),
        enable_tools=True,
        enable_memory=False,
        tool_manager=tool_manager,
    )
    return OrdinaryConversationMissionSubmitter(
        conversation=conversation,
        semantic_validator=semantic_validator,
    )


class ReviewRconSetupExecutor:
    """Render only the closed ScenarioSpec operation catalog to the review server."""

    _FAILURE_MARKERS = (
        "cannot access blocks outside of the world",
        "could not find that entity",
        "failed to execute",
        "incorrect argument",
        "no entity was found",
        "no player was found",
        "that position is not loaded",
        "unable to",
        "unknown or incomplete command",
    )

    def __init__(self, bridge: MinecraftMcpBridge) -> None:
        self._bridge = bridge

    async def execute(self, operation: SetupOperation) -> SetupExecutionResult:
        result = await self._bridge.run_managed_setup(
            render_rcon_command(operation),
            request_id=f"showcase-setup-{operation.operation_id}",
        )
        response = str(result.get("output", ""))
        normalized = response.casefold()
        if not normalized or any(marker in normalized for marker in self._FAILURE_MARKERS):
            raise RuntimeError(f"SCENARIO_SETUP_RCON_FAILED:{operation.operation_id}")
        return SetupExecutionResult(
            operation_id=operation.operation_id,
            outcome="success",
            response_code="OK",
        )


class ReviewScenarioEnvironment:
    """Start one disposable server and Mineflayer runtime before setup mutations."""

    def __init__(
        self,
        *,
        runtime_root: Path,
        bridge: MinecraftMcpBridge,
        profile: str = "managed-review",
        allow_managed_server_create: bool = False,
    ) -> None:
        self.runtime_root = runtime_root.resolve()
        self.bridge = bridge
        self.profile = profile
        self.allow_managed_server_create = allow_managed_server_create
        self._run_id: str | None = None

    async def prepare_disposable_world(self, scenario: ScenarioSpec, run_id: str) -> str:
        if self._run_id is not None:
            raise RuntimeError("showcase runtime already prepared")
        self.runtime_root.mkdir(parents=True, exist_ok=False)
        self._run_id = run_id
        result = await self.bridge.start(
            profile=self.profile,
            request_id=f"showcase-connect-{run_id}",
            allow_server_create=self.allow_managed_server_create,
        )
        if result.get("state") != "ready":
            raise RuntimeError("MINECRAFT_BRIDGE_START_FAILED")
        return "_world"

    async def create_clean_stores(
        self, run_id: str, store_names: tuple[str, ...]
    ) -> tuple[str, ...]:
        if run_id != self._run_id:
            raise RuntimeError("SHOWCASE_RUN_ID_MISMATCH")
        stores = self.runtime_root / "stores"
        stores.mkdir(exist_ok=False)
        refs: list[str] = []
        for name in store_names:
            path = stores / f"{name}.sqlite3"
            path.touch(exist_ok=False)
            refs.append(path.relative_to(self.runtime_root).as_posix())
        return tuple(refs)


class LiveShowcaseBackend:
    """Real model, public tool, projection, and evidence implementation."""

    def __init__(
        self,
        *,
        bridge: MinecraftMcpBridge,
        submitter: MissionSubmitter,
        narrator: EvidenceNarrator,
        capture_probe_path: Path,
        completion_timeout_seconds: float = 1_200,
        event_emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        mission_feedback: Callable[[str, Any, float], Awaitable[None]] | None = None,
        feedback_interval_seconds: float = 240,
    ) -> None:
        if feedback_interval_seconds <= 0 or feedback_interval_seconds > 240:
            raise ValueError("feedback_interval_seconds must be in (0, 240]")
        self._bridge = bridge
        self._submitter = submitter
        self._narrator = narrator
        self._capture_probe_path = capture_probe_path.resolve()
        self._completion_timeout_seconds = completion_timeout_seconds
        self._event_emit = event_emit
        self._mission_feedback = mission_feedback
        self._feedback_interval_seconds = feedback_interval_seconds
        self._following = asyncio.Event()
        self._binding: dict[str, Any] = {}
        self._control_plane: Any = None
        self._caller_scope: str | None = None
        self._bridge.set_viewer_callback(self._on_viewer_event)

    def _on_viewer_event(self, event_type: str, payload: object) -> None:
        if event_type != "client_viewer_status" or not isinstance(payload, dict):
            return
        self._binding = dict(payload)
        if (
            payload.get("binding_state", payload.get("state")) == "following"
            and payload.get("confirmed") is True
        ):
            self._following.set()
        else:
            self._following.clear()

    async def wait_for_readiness(self, *, run_id: str, scenario: ScenarioSpec) -> ViewerReadiness:
        started_at_ms = _now_ms()
        self._control_plane = await configure_voyager_control_plane(
            self._bridge,
            event_emit=self._event_emit,
            blueprint_origins={
                "starter-shelter-v1": (
                    scenario.build_origin.x,
                    scenario.build_origin.y,
                    scenario.build_origin.z,
                )
            },
            entity_origins={
                zone.entity_type: (zone.spawn.x, zone.spawn.y, zone.spawn.z)
                for zone in scenario.monster_zones
            },
            adaptive_frontier=ExplorationFrontier(
                x=scenario.hidden_resources[0].position.x,
                y=scenario.hidden_resources[0].position.y,
                z=scenario.hidden_resources[0].position.z,
                target_block=scenario.hidden_resources[0].item_id,
                target_item="minecraft:raw_copper",
            ),
        )
        async with asyncio.timeout(10 * 60):
            await self._following.wait()
            while True:
                if self._capture_probe_path.is_file():
                    captured_at_ms = self._capture_probe_path.stat().st_mtime_ns // 1_000_000
                    if captured_at_ms >= started_at_ms:
                        break
                await asyncio.sleep(0.25)
        content = self._capture_probe_path.read_bytes()
        binding = self._binding
        return ViewerReadiness(
            username=str(binding.get("username", "")),
            target=str(binding.get("target", "")),
            authenticated=binding.get("username") == scenario.viewer_username,
            spectator=binding.get("mode") == "spectator",
            binding_state="following",
            confirmed=True,
            capture_probe_sha256=hashlib.sha256(content).hexdigest(),
            started_at_ms=started_at_ms,
            finished_at_ms=_now_ms(),
        )

    async def submit_user_text(
        self,
        *,
        run_id: str,
        user_text: str,
        start_mission: Callable[[str], MissionStartBoundary],
    ) -> AdmittedDialogue:
        admitted = await self._submitter.submit_user_text(
            run_id=run_id,
            user_text=user_text,
            start_mission=start_mission,
        )
        _, conversation_id, _ = _showcase_conversation_ids(run_id)
        self._caller_scope = f"conversation:{conversation_id}"
        return admitted

    async def wait_for_completion(
        self, *, run_id: str, mission_id: str
    ) -> ShowcaseEvidenceSnapshot:
        if self._control_plane is None or self._caller_scope is None:
            raise RuntimeError("SHOWCASE_BACKEND_NOT_ADMITTED")
        deadline = asyncio.get_running_loop().time() + self._completion_timeout_seconds
        feedback_started = asyncio.get_running_loop().time()
        last_feedback_at = feedback_started
        last_feedback_signature: tuple[str, int] | None = None
        snapshot = await self._control_plane.mission_repository.snapshot(mission_id)
        while snapshot.mission.status not in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.BLOCKED_UNKNOWN,
        }:
            signature = (snapshot.mission.status.value, len(snapshot.transitions))
            now = asyncio.get_running_loop().time()
            if self._mission_feedback is not None and (
                signature != last_feedback_signature
                or now - last_feedback_at >= self._feedback_interval_seconds
            ):
                await self._mission_feedback(mission_id, snapshot, now - feedback_started)
                last_feedback_signature = signature
                last_feedback_at = now
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("SHOWCASE_MISSION_TIMEOUT")
            await asyncio.sleep(1)
            snapshot = await self._control_plane.mission_repository.snapshot(mission_id)

        if self._mission_feedback is not None:
            await self._mission_feedback(
                mission_id,
                snapshot,
                asyncio.get_running_loop().time() - feedback_started,
            )

        command_ids = tuple(
            dict.fromkeys(
                str(item.details["command_id"])
                for item in snapshot.transitions
                if isinstance(item.details.get("command_id"), str)
            )
        )
        commands = [
            command
            for command_id in command_ids
            if (command := await self._control_plane.repository.get_command(command_id)) is not None
        ]
        steps = [
            step
            for command_id in command_ids
            for step in await self._control_plane.repository.list_steps(command_id)
        ]
        receipts = tuple(step.receipt for step in steps if step.receipt is not None)
        facts = await _mission_world_facts(
            self._control_plane.evidence_collector,
            command_ids,
        )
        advancements = await _mission_advancement_events(
            self._control_plane.evidence_collector,
            command_ids,
        )
        manifest = await self._control_plane.adapter.get_manifest()
        environment = stable_environment_fingerprint(manifest.profile)
        revisions, trusts = await self._control_plane.skill_store.load_live_catalog(
            environment_fingerprint=environment
        )
        prefix = f"mission-{mission_id}-"
        skill_records: list[dict[str, Any]] = []
        for revision_hash, revision in revisions.items():
            if not revision.source_command_id.startswith(prefix):
                continue
            for trust in trusts:
                if trust.revision_hash != revision_hash:
                    continue
                validations = (
                    await self._control_plane.skill_store.load_independent_validation_evidence(
                        revision_hash=revision_hash,
                        environment_fingerprint=environment,
                    )
                )
                skill_records.append(
                    {
                        "revision": revision.model_dump(mode="json"),
                        "trust": trust.model_dump(mode="json"),
                        "independent_validations": tuple(
                            validation.model_dump(mode="json") for validation in validations
                        ),
                    }
                )
        skills = tuple(skill_records)
        with bind_minecraft_caller_scope(self._caller_scope):
            final_status = json.loads(
                await mc_operate_bot.ainvoke(
                    {"operation": "progress", "projection_kind": "missions", "limit": 20}
                )
            )
        evidence_summary = {
            "progress": final_status,
            "mission_status": snapshot.mission.status.value,
            "objective_states": [item.status.value for item in snapshot.objectives],
            "receipt_count": len(receipts),
            "acquired_facts": sum(item.state.value == "acquired" for item in facts),
            "trusted_skills": sum(item["trust"]["status"] == "trusted" for item in skills),
            "advancements_added": _added_advancement_ids(advancements),
        }
        narration_started = _now_ms()
        final_narration = await self._narrator.narrate(evidence_summary)
        narration_finished = _now_ms()

        objective_counts = dict(Counter(item.status.value for item in snapshot.objectives))
        proposal_counts = dict(Counter(item.decision.outcome for item in snapshot.proposals))
        mission_report = MissionReport(
            mission_id=mission_id,
            status=snapshot.mission.status.value,
            objective_counts=objective_counts,
            proposal_counts=proposal_counts,
            budget_used=snapshot.budget.used if snapshot.budget is not None else {},
            evidence_refs=tuple(
                dict.fromkeys(
                    (
                        *(item.evidence_ref for item in snapshot.evidence_links),
                        *(
                            f"receipt:{receipt.get('content_hash')}"
                            for receipt in receipts
                            if isinstance(receipt.get("content_hash"), str)
                        ),
                    )
                )
            ),
            stage_ids=(
                "combat",
                "construction",
                "autonomous-exploration",
                "discovery-acquisition",
                "skill-learning-validation",
                "skill-reuse",
                "progress-projection",
                "final-summary",
            ),
        )
        mission_start = snapshot.mission.created_at_ms
        mission_finish = snapshot.mission.updated_at_ms
        by_intent: dict[str, list[Any]] = {}
        for command in commands:
            goal = command.payload.get("goal", {})
            intent = goal.get("intent") if isinstance(goal, dict) else None
            if isinstance(intent, str):
                by_intent.setdefault(intent, []).append(command)
        combat_span = _command_span(by_intent.get("combat", []), (mission_start, mission_finish))
        build_span = _command_span(by_intent.get("build", []), combat_span)
        travel_span = _command_span(by_intent.get("travel", []), build_span)
        acquire_commands = by_intent.get("acquire", [])
        acquisition_partition = _adaptive_acquisition_stage_spans(
            acquire_commands,
            fallback=travel_span,
        )
        acquire_span = acquisition_partition.discovery_acquisition
        learning_span = acquisition_partition.skill_learning_validation
        reuse_span = acquisition_partition.skill_reuse
        blocked = snapshot.mission.status is MissionStatus.BLOCKED_UNKNOWN

        def failure(code: str, layer: str) -> StageFailure:
            return StageFailure(
                code=code,
                layer=layer,  # type: ignore[arg-type]
                retryable=not blocked,
                operator_action="inspect durable mission and receipt evidence",
            )

        def predicate(
            predicate_id: str, *, expected: object, actual: object, passed: bool
        ) -> VerificationPredicate:
            return VerificationPredicate(
                predicate_id=predicate_id,
                expected=expected,
                actual=actual,
                status="pass" if passed else "fail",
            )

        def checkpoint(
            checkpoint_id: str,
            *,
            passed: bool,
            actual: object,
            verifier: str,
            capability: str | None = None,
        ) -> CheckpointIO:
            return CheckpointIO(
                checkpoint_id=checkpoint_id,
                label=checkpoint_id,
                lifecycle="passed" if passed else ("blocked" if blocked else "failed"),
                decision_source="voyager-controller",
                reason_code="VERIFIED" if passed else "PREDICATE_FAILED",
                selected_capability=capability,
                verifier=verifier,
                predicates=(
                    predicate(
                        f"{checkpoint_id}-verified",
                        expected=True,
                        actual=actual,
                        passed=passed,
                    ),
                ),
                failure=None if passed else failure("PREDICATE_FAILED", "verification"),
            )

        defeated_types = {
            str(combat.get("target_entity_type", "")).removeprefix("minecraft:")
            for receipt in receipts
            if isinstance(receipt, dict)
            and isinstance((combat := receipt.get("combat")), dict)
            and combat.get("outcome") == "defeated"
        }
        combat_checkpoints = tuple(
            checkpoint(
                entity,
                passed=entity in defeated_types,
                actual={"defeated_types": sorted(defeated_types)},
                verifier="EntityDefeated",
                capability="attack",
            )
            for entity in ("zombie", "skeleton", "spider")
        )
        combat_passed = all(item.lifecycle == "passed" for item in combat_checkpoints)

        build_commands = by_intent.get("build", [])
        placement_count = sum(
            receipt.get("capability") == "place"
            for receipt in receipts
            if isinstance(receipt, dict)
        )
        build_passed = bool(build_commands) and all(
            command.state.value in {"succeeded", "succeeded_reconciled"}
            for command in build_commands
        )
        construction_checkpoints = (
            checkpoint(
                "blueprint-selected",
                passed=bool(build_commands),
                actual={"build_commands": len(build_commands)},
                verifier="BlueprintSelected",
            ),
            checkpoint(
                "placements-executed",
                passed=placement_count > 0,
                actual={"placement_receipts": placement_count},
                verifier="PlacementReceiptChain",
                capability="place",
            ),
            checkpoint(
                "region-verified",
                passed=build_passed,
                actual={"build_commands_succeeded": build_passed},
                verifier="StructureMatchesBlueprint",
                capability="inspect_region",
            ),
        )
        construction_passed = all(item.lifecycle == "passed" for item in construction_checkpoints)

        exploration_passed = bool(by_intent.get("travel", []))
        acquired_count = sum(item.state.value == "acquired" for item in facts)
        discovery_passed = acquired_count >= 1
        trusted_count = sum(item["trust"]["status"] == "trusted" for item in skills)
        independent_validations = tuple(
            validation for item in skills for validation in item["independent_validations"]
        )
        learning_resource_refs = tuple(
            str(validation["learning"]["resource_instance_ref"])
            for validation in independent_validations
        )
        validation_resource_refs = tuple(
            str(validation["validation"]["resource_instance_ref"])
            for validation in independent_validations
        )
        independent_resources = any(
            learning_ref != validation_ref
            for learning_ref, validation_ref in zip(
                learning_resource_refs,
                validation_resource_refs,
                strict=True,
            )
        )
        learning_strategy = _selected_strategy(acquire_commands[0]) if acquire_commands else None
        learning_passed = (
            learning_strategy == "learn" and trusted_count >= 1 and independent_resources
        )
        learning_checkpoints = (
            checkpoint(
                "source-a-learning",
                passed=learning_strategy == "learn" and bool(learning_resource_refs),
                actual={
                    "selected_strategy": learning_strategy,
                    "candidate_or_trust_records": len(skills),
                    "learning_resource_refs": learning_resource_refs,
                },
                verifier="LearningReceiptChain",
                capability="collect",
            ),
            checkpoint(
                "source-b-validation",
                passed=learning_passed,
                actual={
                    "selected_strategy": learning_strategy,
                    "trusted_skills": trusted_count,
                    "validation_resource_refs": validation_resource_refs,
                    "resource_instances_independent": independent_resources,
                },
                verifier="IndependentSkillValidation",
                capability="collect",
            ),
        )
        reuse_strategies = tuple(_selected_strategy(command) for command in acquire_commands[1:])
        reuse_count = acquisition_partition.reuse_command_count
        reuse_passed = reuse_count >= 1 and all(strategy == "live" for strategy in reuse_strategies)
        reuse_checkpoints = (
            checkpoint(
                "source-c-reuse",
                passed=reuse_passed,
                actual={
                    "trusted_reuse_goals": reuse_count,
                    "selected_strategies": reuse_strategies,
                },
                verifier="TrustedSkillReuse",
                capability="collect",
            ),
        )
        advancement_ids = _added_advancement_ids(advancements)
        progress_passed = len(advancement_ids) >= 2
        summary_passed = snapshot.mission.status is MissionStatus.COMPLETED and bool(
            final_narration.strip()
        )

        def stage(
            stage_id: str,
            span: tuple[int, int],
            *,
            passed: bool,
            verifier: str,
            actual: object,
            checkpoints: tuple[CheckpointIO, ...] = (),
            capability: str | None = None,
        ) -> StageEvidence:
            return StageEvidence(
                stage_id=stage_id,
                lifecycle="passed" if passed else ("blocked" if blocked else "failed"),
                started_at_ms=span[0],
                finished_at_ms=max(span),
                decision_source="voyager-controller",
                reason_code="VERIFIED" if passed else "PREDICATE_FAILED",
                selected_capability=capability,
                verifier=verifier,
                predicates=(
                    predicate(
                        f"{stage_id}-verified",
                        expected=True,
                        actual=actual,
                        passed=passed,
                    ),
                ),
                checkpoints=checkpoints,
                failure=None if passed else failure("PREDICATE_FAILED", "verification"),
            )

        stages = (
            stage(
                "combat",
                combat_span,
                passed=combat_passed,
                verifier="EntityDefeated",
                actual={"defeated_types": sorted(defeated_types)},
                checkpoints=combat_checkpoints,
                capability="attack",
            ),
            stage(
                "construction",
                build_span,
                passed=construction_passed,
                verifier="StructureMatchesBlueprint",
                actual={"placement_receipts": placement_count},
                checkpoints=construction_checkpoints,
                capability="place",
            ),
            stage(
                "autonomous-exploration",
                travel_span,
                passed=exploration_passed,
                verifier="BoundedExploration",
                actual={"travel_goals": len(by_intent.get("travel", []))},
                capability="goto",
            ),
            stage(
                "discovery-acquisition",
                acquire_span,
                passed=discovery_passed,
                verifier="WorldFactAcquired",
                actual={"acquired_facts": acquired_count},
                capability="collect",
            ),
            stage(
                "skill-learning-validation",
                learning_span,
                passed=learning_passed,
                verifier="IndependentSkillValidation",
                actual={"trusted_skills": trusted_count},
                checkpoints=learning_checkpoints,
                capability="collect",
            ),
            stage(
                "skill-reuse",
                reuse_span,
                passed=reuse_passed,
                verifier="TrustedSkillReuse",
                actual={
                    "trusted_reuse_goals": reuse_count,
                    "selected_strategies": reuse_strategies,
                },
                checkpoints=reuse_checkpoints,
                capability="collect",
            ),
            stage(
                "progress-projection",
                (mission_start, mission_finish),
                passed=progress_passed,
                verifier="VanillaAdvancementAdded",
                actual={"advancement_ids": advancement_ids},
            ),
            stage(
                "final-summary",
                (narration_started, narration_finished),
                passed=summary_passed,
                verifier="EvidenceOnlyNarration",
                actual={
                    "mission_status": snapshot.mission.status.value,
                    "narration_nonempty": bool(final_narration.strip()),
                },
            ),
        )
        return ShowcaseEvidenceSnapshot(
            run_id=run_id,
            mission_id=mission_id,
            proposals=tuple(item.model_dump(mode="json") for item in snapshot.proposals),
            commands=tuple(item.model_dump(mode="json") for item in commands),
            receipts=receipts,
            discoveries=tuple(item.model_dump(mode="json") for item in facts),
            skills=skills,
            advancements=tuple(item.model_dump(mode="json") for item in advancements),
            mission_report=mission_report,
            final_status=final_status,
            final_narration=final_narration,
            stages=stages,
        )

    async def close(self) -> None:
        try:
            await self._submitter.close()
        finally:
            try:
                await self._narrator.close()
            finally:
                try:
                    if self._bridge.is_running:
                        await self._bridge.shutdown_runtime(
                            request_id=(
                                f"showcase-shutdown-{uuid5(NAMESPACE_URL, str(time.time_ns()))}"
                            )
                        )
                finally:
                    await cleanup_bridge()


class DesktopShowcaseCapture:
    """Record the fresh Windows desktop and retain a bounded screenshot ring."""

    def __init__(self, *, working_root: Path, frame_interval_seconds: float = 1.0) -> None:
        self.working_root = working_root.resolve()
        self.capture_probe_path = self.working_root / "latest-frame.png"
        self._frame_interval_seconds = frame_interval_seconds
        self._frames: deque[tuple[int, Path]] = deque()
        self._video_path = self.working_root / "complete-run.mp4"
        self._video_started_at_ms: int | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._frame_task: asyncio.Task[None] | None = None
        self._closing = False

    async def start(self, *, run_id: str) -> None:
        del run_id
        self.working_root.mkdir(parents=True, exist_ok=False)
        self._video_started_at_ms = _now_ms()
        self._process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "gdigrab",
            "-framerate",
            "10",
            "-i",
            "desktop",
            "-vf",
            "scale=1280:-2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            str(self._video_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._closing = False
        self._frame_task = asyncio.create_task(
            self._capture_frames(), name="minecraft-showcase-desktop-capture"
        )

    @staticmethod
    def _grab_frame(path: Path, probe_path: Path) -> None:
        image = ImageGrab.grab(all_screens=True)
        image.thumbnail((1600, 1000))
        image.save(path, format="PNG", optimize=True)
        image.save(probe_path, format="PNG", optimize=True)

    async def _capture_frames(self) -> None:
        while not self._closing:
            captured_at_ms = _now_ms()
            path = self.working_root / f"frame-{captured_at_ms}.png"
            await asyncio.to_thread(self._grab_frame, path, self.capture_probe_path)
            self._frames.append((captured_at_ms, path))
            while len(self._frames) > 30:
                _, expired = self._frames.popleft()
                with contextlib.suppress(OSError):
                    expired.unlink()
            await asyncio.sleep(self._frame_interval_seconds)

    async def _stop(self) -> int:
        self._closing = True
        if self._frame_task is not None:
            await asyncio.gather(self._frame_task, return_exceptions=True)
            self._frame_task = None
        process = self._process
        self._process = None
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.write(b"q\n")
                await process.stdin.drain()
            try:
                await asyncio.wait_for(process.wait(), timeout=20)
            except TimeoutError:
                process.terminate()
                await process.wait()
        return _now_ms()

    async def collect(
        self, *, run_id: str, mission_id: str, stages: tuple[Any, ...]
    ) -> MediaCaptureBundle:
        del run_id, mission_id
        video_finished_at_ms = await self._stop()
        final_stage_finish = stages[-1].finished_at_ms
        eligible = [item for item in self._frames if item[0] <= final_stage_finish]
        if not eligible:
            raise RuntimeError("NO_FRESH_SCREENSHOT_WITHIN_SHOWCASE_STAGE")
        captured_at_ms, screenshot_path = eligible[-1]
        stage_ids = tuple(stage.stage_id for stage in stages)
        if self._video_started_at_ms is None or not self._video_path.is_file():
            raise RuntimeError("SHOWCASE_VIDEO_MISSING")
        return MediaCaptureBundle(
            screenshots=(
                CapturedMedia(
                    artifact_id="fresh-desktop-walkthrough",
                    kind="screenshot",
                    content=screenshot_path.read_bytes(),
                    suffix=".png",
                    captured_at_ms=captured_at_ms,
                    media_started_at_ms=captured_at_ms,
                    media_finished_at_ms=captured_at_ms,
                    stage_ids=stage_ids,
                ),
            ),
            video=CapturedMedia(
                artifact_id="complete-run-video",
                kind="video",
                content=self._video_path.read_bytes(),
                suffix=".mp4",
                captured_at_ms=stages[0].started_at_ms,
                media_started_at_ms=self._video_started_at_ms,
                media_finished_at_ms=video_finished_at_ms,
                stage_ids=stage_ids,
            ),
        )

    async def abort(self) -> None:
        await self._stop()
