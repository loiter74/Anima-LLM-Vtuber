"""Trusted-only live execution and evidence-isolated fallback."""

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
    SkillExecutionResult,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import (
    Skill,
    SkillProvenance,
    SkillTrustStage,
)
from animetta.tools.minecraft.voyager.contracts import VoyagerMode, VoyagerSessionContext
from animetta.tools.minecraft.voyager.policy import VoyagerPolicy
from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository


def _live():
    return importlib.import_module("animetta.tools.minecraft.voyager.live")


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


def _skill(skill_id: str, stage: SkillTrustStage) -> Skill:
    return Skill(
        id=skill_id,
        name="collect wood",
        description=skill_id,
        body={"type": "code", "code": "await collect('oak_log', 1)"},
        success_count=5,
        validated=stage is SkillTrustStage.TRUSTED,
        trust_stage=stage,
        provenance=SkillProvenance(
            source_session_id="learn-session",
            source_task_id="wood-task",
            policy_report={"allowed": True},
            evidence_refs=["source-receipt"],
            validation_session_id=("validation-task" if stage is SkillTrustStage.TRUSTED else ""),
            environment_fingerprint="test",
        ),
    )


class FakeRuntime:
    is_running = True

    def __init__(self, *, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.calls = []

    async def eval_skill(self, code: str, **kwargs):
        self.calls.append((code, kwargs))
        started = datetime(2026, 7, 12, tzinfo=UTC)
        receipt = ActionReceipt(
            receipt_id=f"receipt-{len(self.calls)}",
            session_id=kwargs["session_id"],
            task_id=kwargs["task_id"],
            correlation_id=kwargs["correlation_id"],
            runtime_id="runtime-1",
            capability="collect",
            params={"block_type": "oak_log", "count": 1},
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            before_observation_hash="before",
            after_observation_hash="after",
            outcome=ActionOutcome.SUCCESS if self.succeeds else ActionOutcome.ERROR,
            error=(
                None
                if self.succeeds
                else ActionError(code="RESOURCE_NOT_FOUND", message="no tree")
            ),
        )
        return SkillExecutionResult(receipts=[receipt])


class FakeFallback:
    def __init__(self) -> None:
        self.calls = []

    async def run_goal(self, goal: str, *, reason: str, parent_task_id: str):
        self.calls.append((goal, reason, parent_task_id))
        return {
            "outcome": "fallback",
            "fallback": True,
            "fallback_task_id": f"fallback-{parent_task_id}",
            "evidence_eligible": False,
            "reason": reason,
        }


def _session(runtime, library, fallback, *, threshold: int = 3):
    live = _live()
    context = VoyagerSessionContext(
        session_id="live-session-1",
        mode=VoyagerMode.LIVE,
        runtime=runtime,
        manifest=_manifest(),
        authorized_capabilities=frozenset({"collect"}),
        repository=InMemoryVoyagerRepository(),
    )
    return live.LiveSession(
        context=context,
        library=library,
        policy=VoyagerPolicy(supported_protocol="1.0", allowed_capabilities={"collect"}),
        fallback=fallback,
        degrade_threshold=threshold,
    )


async def test_live_executes_only_trusted_skill_and_returns_receipt_evidence() -> None:
    library = SkillLibrary()
    await library.save_skill(_skill("candidate", SkillTrustStage.CANDIDATE))
    await library.save_skill(_skill("trusted", SkillTrustStage.TRUSTED))
    runtime = FakeRuntime()
    session = _session(runtime, library, FakeFallback())

    result = await session.run_goal("collect wood")

    assert result["outcome"] == "success"
    assert result["skill_id"] == "trusted"
    assert result["evidence_eligible"] is True
    assert result["receipt_hashes"]
    assert len(runtime.calls) == 1


async def test_no_trusted_skill_uses_evidence_isolated_fallback() -> None:
    library = SkillLibrary()
    await library.save_skill(_skill("candidate", SkillTrustStage.CANDIDATE))
    fallback = FakeFallback()
    session = _session(FakeRuntime(), library, fallback)

    result = await session.run_goal("collect wood")

    assert result["outcome"] == "fallback"
    assert result["evidence_eligible"] is False
    assert result["reason"] == "no_trusted_skill"
    assert fallback.calls[0][2] not in result["fallback_task_id"] or result["fallback_task_id"].startswith("fallback-")


async def test_live_failure_demotes_after_consecutive_threshold_and_falls_back() -> None:
    library = SkillLibrary()
    skill = _skill("trusted", SkillTrustStage.TRUSTED)
    skill.consecutive_failures = 2
    await library.save_skill(skill)
    fallback = FakeFallback()
    session = _session(FakeRuntime(succeeds=False), library, fallback, threshold=3)

    result = await session.run_goal("collect wood")
    loaded = await library.get_skill(skill.id)

    assert result["outcome"] == "fallback"
    assert result["evidence_eligible"] is False
    assert result["failed_receipt_hashes"]
    assert loaded.trust_stage is SkillTrustStage.CANDIDATE
    assert loaded.provenance.history[-1]["event"] == "demoted"


async def test_policy_rejection_never_calls_runtime_and_falls_back() -> None:
    library = SkillLibrary()
    skill = _skill("unsafe", SkillTrustStage.TRUSTED)
    skill.body["code"] = "process.exit(0)"
    await library.save_skill(skill)
    runtime = FakeRuntime()
    session = _session(runtime, library, FakeFallback())

    result = await session.run_goal("collect wood")

    assert result["outcome"] == "fallback"
    assert result["reason"].startswith("policy_rejected")
    assert runtime.calls == []


async def test_fallback_session_uses_separate_task_and_never_returns_unlock_evidence() -> None:
    live = _live()
    calls = []

    async def runner(goal: str, *, task_id: str):
        calls.append((goal, task_id))
        return {"completed": True, "receipt_hashes": ["fallback-receipt"]}

    context = VoyagerSessionContext(
        session_id="fallback-session-1",
        mode=VoyagerMode.FALLBACK,
        runtime=FakeRuntime(),
        manifest=_manifest(),
        authorized_capabilities=frozenset({"collect"}),
        repository=InMemoryVoyagerRepository(),
    )
    session = live.FallbackSession(context=context, runner=runner)

    result = await session.run_goal(
        "collect wood",
        reason="live skill failed",
        parent_task_id="live-parent-task",
    )

    assert result["outcome"] == "fallback"
    assert result["evidence_eligible"] is False
    assert result["parent_task_id"] == "live-parent-task"
    assert result["fallback_task_id"] != "live-parent-task"
    assert calls == [("collect wood", result["fallback_task_id"])]
    assert "receipt_hashes" not in result
