"""Mocked JSON-line runtime integration from learning evidence to live reuse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from animetta.tools.gamebot.contracts import (
    ActionOutcome,
    ActionReceipt,
    CapabilityManifest,
    CapabilityRisk,
    GameBotCapability,
    GameBotObservation,
    SkillExecutionResult,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.voyager.adapter import MinecraftGameBotAdapter
from animetta.tools.minecraft.voyager.contracts import (
    VoyagerMode,
    VoyagerSessionContext,
)
from animetta.tools.minecraft.voyager.learning import LearningSession
from animetta.tools.minecraft.voyager.live import LiveSession
from animetta.tools.minecraft.voyager.policy import VoyagerPolicy
from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository
from animetta.tools.minecraft.voyager.tech_graph import (
    FrontierScheduler,
    TechGraph,
    TechNode,
    TechProgress,
)


class FakeNodeBridge:
    """Emit the same payload shapes as the external Node capability runtime."""

    is_running = True

    def __init__(self) -> None:
        self.inventory: dict[str, int] = {}
        self.sequence = 0
        self.last_observation: GameBotObservation | None = None
        self.pending_observation: GameBotObservation | None = None

    def _observation(self, correlation_id: str) -> GameBotObservation:
        self.sequence += 1
        return GameBotObservation(
            observation_id=f"observation-{self.sequence}",
            correlation_id=correlation_id,
            runtime_id="node-runtime-1",
            captured_at=datetime(2026, 7, 12, tzinfo=UTC)
            + timedelta(seconds=self.sequence),
            inventory=dict(self.inventory),
            equipment={},
            environment={"dimension": "overworld"},
        )

    async def send_command(self, action, params, timeout=60.0):
        del timeout
        if action == "capabilities":
            manifest = CapabilityManifest(
                protocol_version="1.0",
                runtime_id="node-runtime-1",
                capabilities=[
                    GameBotCapability(
                        name="collect",
                        risk=CapabilityRisk.SURVIVAL_SAFE,
                        parameters={},
                    )
                ],
            )
            return {"status": "success", "result": manifest.model_dump(mode="json")}

        if action == "observe":
            observation = self.pending_observation or self._observation(
                params["correlation_id"]
            )
            self.pending_observation = None
            self.last_observation = observation
            return {
                "status": "success",
                "result": observation.model_dump(mode="json"),
            }

        if action == "eval_skill":
            assert self.last_observation is not None
            self.inventory["oak_log"] = self.inventory.get("oak_log", 0) + 1
            after = self._observation(f'{params["correlation_id"]}:after')
            receipt = ActionReceipt(
                receipt_id=f"receipt-{self.sequence}",
                session_id=params["session_id"],
                task_id=params["task_id"],
                correlation_id=f'{params["correlation_id"]}:1:collect',
                runtime_id="node-runtime-1",
                capability="collect",
                params={"block_type": "oak_log", "count": 1},
                started_at=after.captured_at,
                finished_at=after.captured_at + timedelta(seconds=1),
                before_observation_hash=self.last_observation.content_hash,
                after_observation_hash=after.content_hash,
                outcome=ActionOutcome.SUCCESS,
            )
            self.pending_observation = after
            result = SkillExecutionResult(receipts=[receipt], output={"collected": 1})
            return {"status": "success", "result": result.model_dump(mode="json")}

        raise AssertionError(f"unexpected Node command: {action}")


class Generator:
    async def generate(self, **kwargs) -> str:
        return "await collect('oak_log', 1);"


class UnusedFallback:
    async def run_goal(self, goal, *, reason, parent_task_id):
        raise AssertionError((goal, reason, parent_task_id))


async def test_mocked_node_learning_promotes_then_live_reuses_trusted_skill() -> None:
    bridge = FakeNodeBridge()
    runtime = MinecraftGameBotAdapter(bridge)
    manifest = await runtime.get_capabilities()
    repository = InMemoryVoyagerRepository()
    library = SkillLibrary()
    policy = VoyagerPolicy(
        supported_protocol="1.0",
        allowed_capabilities={"collect"},
    )
    graph = TechGraph(
        [
            TechNode(
                id="wood_collection",
                name="Collect wood",
                allowed_capabilities=frozenset({"collect"}),
                required_capabilities=("collect",),
                postconditions={"oak_log": 1},
            )
        ]
    )
    learn_context = VoyagerSessionContext(
        session_id="learn-session",
        mode=VoyagerMode.LEARN,
        runtime=runtime,
        manifest=manifest,
        authorized_capabilities=frozenset({"collect"}),
        repository=repository,
    )
    learning = LearningSession(
        context=learn_context,
        graph=graph,
        scheduler=FrontierScheduler(graph),
        policy=policy,
        library=library,
        code_generator=Generator(),
        progress=TechProgress(),
    )

    learned = await learning.run_once()

    assert learned.status == "trusted"
    trusted = await library.match_trusted_skills({}, limit=5)
    assert len(trusted) == 1

    live_context = VoyagerSessionContext(
        session_id="live-session",
        mode=VoyagerMode.LIVE,
        runtime=runtime,
        manifest=manifest,
        authorized_capabilities=frozenset({"collect"}),
        repository=repository,
    )
    live = LiveSession(
        context=live_context,
        library=library,
        policy=policy,
        fallback=UnusedFallback(),
    )

    result = await live.run_goal("collect wood")

    assert result["outcome"] == "success"
    assert result["skill_id"] == trusted[0].id
    assert result["evidence_eligible"] is True
    assert bridge.inventory["oak_log"] == 3
