"""Cheat-free learning session driven by the reachable technology frontier."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from animetta.tools.gamebot.contracts import (
    ActionError,
    ActionOutcome,
    ActionReceipt,
    CapabilityManifest,
    CapabilityRisk,
    GameBotCapability,
    GameBotObservation,
    GameBotPosition,
    SkillExecutionResult,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import SkillTrustStage
from animetta.tools.minecraft.voyager.contracts import (
    VoyagerMode,
    VoyagerSessionContext,
)
from animetta.tools.minecraft.voyager.policy import VoyagerPolicy
from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository
from animetta.tools.minecraft.voyager.tech_graph import (
    FrontierScheduler,
    TechProgress,
    build_survival_tech_graph,
)


def _learning():
    return importlib.import_module("animetta.tools.minecraft.voyager.learning")


def _observation(observation_id: str, inventory: dict[str, int]):
    return GameBotObservation(
        observation_id=observation_id,
        correlation_id=f"corr-{observation_id}",
        runtime_id="runtime-1",
        captured_at=datetime(2026, 7, 12, tzinfo=UTC),
        health=20,
        food=20,
        inventory=inventory,
        environment={"biome": "plains", "seed_fingerprint": "seed-123"},
    )


class FakeGenerator:
    def __init__(self, code: str = "await collect('oak_log', 1)") -> None:
        self.code = code
        self.calls: list[dict] = []

    async def generate(self, *, node, observation, feedback, relevant_skills):
        self.calls.append(
            {
                "node": node,
                "observation": observation,
                "feedback": list(feedback),
                "relevant_skills": list(relevant_skills),
            }
        )
        return self.code


class FakeLearningRuntime:
    is_running = True

    def __init__(self, executions: list[tuple[GameBotObservation, GameBotObservation, bool]]):
        self._executions = list(executions)
        self._observation_queue: list[GameBotObservation] = []
        for before, after, _ in executions:
            self._observation_queue.extend([before, after])
        self._current_before: GameBotObservation | None = None
        self.eval_calls: list[dict] = []

    async def get_capabilities(self):
        return _manifest()

    async def observe(self, correlation_id: str):
        observation = self._observation_queue.pop(0)
        if self._current_before is None:
            self._current_before = observation
        else:
            self._current_before = None
        return observation

    async def eval_skill(
        self,
        code: str,
        *,
        allowed_capabilities: list[str],
        session_id: str,
        task_id: str,
        correlation_id: str,
        timeout: float = 60.0,
    ):
        index = len(self.eval_calls)
        before, after, succeeds = self._executions[index]
        self.eval_calls.append(
            {
                "code": code,
                "allowed_capabilities": allowed_capabilities,
                "session_id": session_id,
                "task_id": task_id,
                "correlation_id": correlation_id,
            }
        )
        started = datetime(2026, 7, 12, tzinfo=UTC) + timedelta(seconds=index)
        receipt = ActionReceipt(
            receipt_id=f"receipt-{index}",
            session_id=session_id,
            task_id=task_id,
            correlation_id=f"receipt-corr-{index}",
            runtime_id="runtime-1",
            capability="collect",
            params={"block_type": "oak_log", "count": 1},
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            before_observation_hash=before.content_hash,
            after_observation_hash=after.content_hash,
            outcome=ActionOutcome.SUCCESS if succeeds else ActionOutcome.ERROR,
            error=(
                None
                if succeeds
                else ActionError(code="RESOURCE_NOT_FOUND", message="no tree", retryable=True)
            ),
        )
        return SkillExecutionResult(receipts=[receipt], output={"ok": succeeds})


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        protocol_version="1.0",
        runtime_id="runtime-1",
        capabilities=[
            GameBotCapability(
                name="collect",
                risk=CapabilityRisk.SURVIVAL_SAFE,
                parameters={},
            )
        ],
    )


def _session(runtime, generator, *, scheduler=None):
    learning = _learning()
    graph = build_survival_tech_graph()
    library = SkillLibrary()
    context = VoyagerSessionContext(
        session_id="learn-session-1",
        mode=VoyagerMode.LEARN,
        runtime=runtime,
        manifest=_manifest(),
        authorized_capabilities=frozenset({"collect"}),
        repository=InMemoryVoyagerRepository(),
        goal="",
    )
    session = learning.LearningSession(
        context=context,
        graph=graph,
        scheduler=scheduler or FrontierScheduler(graph),
        policy=VoyagerPolicy(supported_protocol="1.0", allowed_capabilities={"collect"}),
        library=library,
        code_generator=generator,
        progress=TechProgress(),
        max_attempts=4,
    )
    return session, library


async def test_learning_selects_reachable_frontier_node() -> None:
    before = _observation("before-source", {})
    after = _observation("after-source", {"oak_log": 1})
    validation_before = _observation("before-validation", {"oak_log": 1})
    validation_after = _observation("after-validation", {"oak_log": 2})
    generator = FakeGenerator()
    session, _ = _session(
        FakeLearningRuntime(
            [(before, after, True), (validation_before, validation_after, True)]
        ),
        generator,
    )

    outcome = await session.run_once()

    assert outcome.node_id == "wood_collection"
    assert generator.calls[0]["node"].id == "wood_collection"
    assert "iron_pickaxe" not in generator.calls[0]["node"].prerequisites


async def test_learning_retries_four_times_with_structured_feedback_then_cools_node() -> None:
    executions = []
    for index in range(4):
        executions.append(
            (
                _observation(f"before-{index}", {}),
                _observation(f"after-{index}", {}),
                False,
            )
        )
    generator = FakeGenerator()
    graph = build_survival_tech_graph()
    scheduler = FrontierScheduler(graph, failure_cooldown=1)
    session, _ = _session(FakeLearningRuntime(executions), generator, scheduler=scheduler)

    failed = await session.run_once()
    discovery = await session.run_once()

    assert failed.status == "failed"
    assert failed.attempts == 4
    assert failed.feedback[-1] == "RESOURCE_NOT_FOUND: no tree"
    assert len(generator.calls) == 4
    assert generator.calls[1]["feedback"][-1] == "RESOURCE_NOT_FOUND: no tree"
    assert discovery.status == "discovery"
    assert discovery.discovery.radius <= 128
    assert discovery.discovery.seconds <= 600


async def test_runtime_transport_exception_becomes_bounded_feedback() -> None:
    class TransportFailureRuntime(FakeLearningRuntime):
        def __init__(self, executions):
            super().__init__(executions)
            self.cancelled: list[str] = []
            self.health_checks = 0

        async def eval_skill(self, code: str, **identity):
            self.eval_calls.append({"code": code, **identity})
            raise TimeoutError("runtime transport timed out")

        async def cancel_action(self, correlation_id: str):
            self.cancelled.append(correlation_id)
            return {"cancelled": True}

        async def health(self):
            self.health_checks += 1
            return {"healthy": True, "busy": self.health_checks % 2 == 1}

    observations = [
        (_observation(f"before-{index}", {}), _observation(f"unused-{index}", {}), True)
        for index in range(4)
    ]
    runtime = TransportFailureRuntime(observations)
    session, _ = _session(runtime, FakeGenerator())

    outcome = await session.run_once()

    assert outcome.status == "failed"
    assert outcome.attempts == 4
    assert outcome.feedback[-1].startswith("RUNTIME_ERROR:TimeoutError")
    assert runtime.cancelled == [
        call["correlation_id"] for call in runtime.eval_calls
    ]
    assert runtime.health_checks == 8


async def test_first_success_creates_candidate_then_independent_task_promotes_trusted() -> None:
    source_before = _observation("source-before", {})
    source_after = _observation("source-after", {"oak_log": 1})
    validation_before = _observation("validation-before", {"oak_log": 1})
    validation_after = _observation("validation-after", {"oak_log": 2})
    runtime = FakeLearningRuntime(
        [(source_before, source_after, True), (validation_before, validation_after, True)]
    )
    session, library = _session(runtime, FakeGenerator())

    outcome = await session.run_once()
    skills = await library.get_all_skills()

    assert outcome.status == "trusted"
    assert len(skills) == 1
    assert skills[0].trust_stage is SkillTrustStage.TRUSTED
    assert skills[0].is_trusted is True
    assert skills[0].provenance.source_task_id != skills[0].provenance.validation_session_id
    assert runtime.eval_calls[0]["task_id"] != runtime.eval_calls[1]["task_id"]
    assert session.progress.unlocked_nodes == {"wood_collection"}
    checkpoint = await session._context.repository.last_checkpoint("learn-session-1")
    assert checkpoint.task_id == skills[0].provenance.validation_session_id
    assert checkpoint.metadata["inventory"] == {"oak_log": 2}


async def test_failed_independent_validation_leaves_candidate_out_of_live_trust() -> None:
    runtime = FakeLearningRuntime(
        [
            (
                _observation("source-before", {}),
                _observation("source-after", {"oak_log": 1}),
                True,
            ),
            (
                _observation("validation-before", {"oak_log": 1}),
                _observation("validation-after", {"oak_log": 1}),
                False,
            ),
        ]
    )
    session, library = _session(runtime, FakeGenerator())

    outcome = await session.run_once()
    skill = (await library.get_all_skills())[0]

    assert outcome.status == "candidate"
    assert outcome.feedback == ("RESOURCE_NOT_FOUND: no tree",)
    assert skill.trust_stage is SkillTrustStage.CANDIDATE
    assert skill.is_trusted is False
    assert skill.provenance.validation_session_id == ""


async def test_learning_module_has_no_admin_or_fixed_identity_dependencies() -> None:
    source = importlib.import_module("inspect").getsource(_learning())

    for forbidden in ("rcon_helpers", "_rcon(", "AnimettaBot", "DeepSeekLLM", "AsyncOpenAI"):
        assert forbidden not in source


async def test_bounded_discovery_executes_authorized_goto_without_unlocking_tech() -> None:
    learning = _learning()
    graph = build_survival_tech_graph()
    scheduler = FrontierScheduler(graph, failure_cooldown=1)
    scheduler.record_failure("wood_collection")
    before = _observation("discovery-before", {})
    before = before.model_copy(update={"position": GameBotPosition(x=0, y=64, z=0)})
    after = _observation("discovery-after", {})
    after = after.model_copy(update={"position": GameBotPosition(x=32, y=64, z=0)})

    class DiscoveryRuntime:
        is_running = True

        def __init__(self):
            self.observations = [before, after]
            self.actions = []

        async def observe(self, correlation_id: str):
            return self.observations.pop(0)

        async def execute_action(self, capability, params, **identity):
            self.actions.append((capability, params, identity))
            started = datetime(2026, 7, 12, tzinfo=UTC)
            return ActionReceipt(
                receipt_id="discovery-receipt",
                session_id=identity["session_id"],
                task_id=identity["task_id"],
                correlation_id=identity["correlation_id"],
                runtime_id="runtime-1",
                capability=capability,
                params=params,
                started_at=started,
                finished_at=started + timedelta(seconds=1),
                before_observation_hash=before.content_hash,
                after_observation_hash=after.content_hash,
                outcome=ActionOutcome.SUCCESS,
            )

    runtime = DiscoveryRuntime()
    manifest = CapabilityManifest(
        protocol_version="1.0",
        runtime_id="runtime-1",
        capabilities=[
            GameBotCapability(name="collect", risk=CapabilityRisk.SURVIVAL_SAFE),
            GameBotCapability(name="goto", risk=CapabilityRisk.SURVIVAL_SAFE),
        ],
    )
    context = VoyagerSessionContext(
        session_id="learn-session-1",
        mode=VoyagerMode.LEARN,
        runtime=runtime,
        manifest=manifest,
        authorized_capabilities=frozenset({"collect", "goto"}),
        repository=InMemoryVoyagerRepository(),
    )
    session = learning.LearningSession(
        context=context,
        graph=graph,
        scheduler=scheduler,
        policy=VoyagerPolicy(
            supported_protocol="1.0", allowed_capabilities={"collect", "goto"}
        ),
        library=SkillLibrary(),
        code_generator=FakeGenerator(),
        progress=TechProgress(),
    )

    outcome = await session.run_once()

    capability, params, identity = runtime.actions[0]
    assert outcome.status == "discovery"
    assert capability == "goto"
    assert abs(params["x"] - before.position.x) <= outcome.discovery.radius
    assert abs(params["z"] - before.position.z) <= outcome.discovery.radius
    assert identity["timeout"] <= outcome.discovery.seconds
    assert session.progress.unlocked_nodes == frozenset()


async def test_llm_code_generator_uses_frontier_and_feedback_and_strips_fences() -> None:
    learning = _learning()

    class FakeLLM:
        def __init__(self):
            self.messages = None

        async def chat(self, messages):
            self.messages = messages
            return type(
                "Response",
                (),
                {"content": "```javascript\nawait collect('oak_log', 1);\n```"},
            )()

    llm = FakeLLM()
    generator = learning.FrontierLLMCodeGenerator(llm)
    node = build_survival_tech_graph().get("wood_collection")

    code = await generator.generate(
        node=node,
        observation=_observation("obs-generator", {}),
        feedback=["RESOURCE_NOT_FOUND: no tree"],
        relevant_skills=[],
    )

    assert code == "await collect('oak_log', 1);"
    prompt = llm.messages[-1]["content"]
    assert "wood_collection" in prompt
    assert "RESOURCE_NOT_FOUND" in prompt
