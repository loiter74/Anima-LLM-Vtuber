"""Reachable-frontier learning without RCON or direct world mutation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from animetta.tools.gamebot.contracts import (
    ActionOutcome,
    GameBotObservation,
    SkillExecutionResult,
)
from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import (
    Skill,
    SkillProvenance,
    SkillTrustStage,
)

from .contracts import VoyagerCheckpoint, VoyagerSessionContext
from .policy import PolicyReport, VoyagerPolicy
from .tech_graph import (
    DiscoveryTask,
    FrontierScheduler,
    TechEvidenceVerifier,
    TechGraph,
    TechNode,
    TechProgress,
)


class LearningCodeGenerator(Protocol):
    async def generate(
        self,
        *,
        node: TechNode,
        observation: Any,
        feedback: list[str],
        relevant_skills: list[Skill],
    ) -> str: ...


class FrontierLLMCodeGenerator:
    """Generate one policy-constrained strategy for a selected frontier node."""

    def __init__(self, llm_service: Any) -> None:
        self._llm = llm_service

    async def generate(
        self,
        *,
        node: TechNode,
        observation: Any,
        feedback: list[str],
        relevant_skills: list[Skill],
    ) -> str:
        observation_payload = (
            observation.model_dump(mode="json")
            if hasattr(observation, "model_dump")
            else observation
        )
        skill_context = [
            {
                "name": skill.name,
                "description": skill.description,
                "code": str((skill.body or {}).get("code", "")),
            }
            for skill in relevant_skills
        ]
        prompt = (
            "Generate JavaScript for exactly one Minecraft survival technology task.\n"
            f"Frontier node: {node.id} ({node.name})\n"
            f"Required capabilities: {list(node.required_capabilities)}\n"
            f"Allowed capability wrappers: {sorted(node.allowed_capabilities)}\n"
            f"Postconditions: {node.postconditions}\n"
            f"Observation: {json.dumps(observation_payload, ensure_ascii=False, default=str)}\n"
            f"Previous feedback: {json.dumps(feedback, ensure_ascii=False)}\n"
            f"Relevant skills: {json.dumps(skill_context, ensure_ascii=False)}\n"
            "Use only the listed async capability wrappers. Return JavaScript only."
        )
        response = await self._llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You write minimal survival-safe Minecraft bot skills. "
                        "Never use process, modules, network, administrator commands, "
                        "dynamic code, raw bot access, or world-state mutation."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        content = str(getattr(response, "content", response)).strip()
        if content.startswith("```") and content.endswith("```"):
            lines = content.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()
        return content


class LearningOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["trusted", "candidate", "failed", "discovery"]
    node_id: str = ""
    skill_id: str = ""
    attempts: int = 0
    discovery: DiscoveryTask | None = None
    feedback: tuple[str, ...] = ()


def _execution_failure(execution: SkillExecutionResult) -> str | None:
    if not execution.receipts:
        return "EMPTY_RECEIPT_CHAIN: skill emitted no action evidence"
    for receipt in execution.receipts:
        if receipt.outcome is not ActionOutcome.SUCCESS:
            if receipt.error is not None:
                return f"{receipt.error.code}: {receipt.error.message}"
            return f"ACTION_{receipt.outcome.value.upper()}: {receipt.receipt_id}"
    return None


def _environment_fingerprint(runtime_id: str, environment: dict[str, Any]) -> str:
    encoded = json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()
    return f"runtime:{runtime_id}|env:{hashlib.sha256(encoded).hexdigest()}"


class LearningSession:
    """One cancellable learning session owned exclusively by VoyagerController."""

    def __init__(
        self,
        *,
        context: VoyagerSessionContext,
        graph: TechGraph,
        scheduler: FrontierScheduler,
        policy: VoyagerPolicy,
        library: SkillLibrary,
        code_generator: LearningCodeGenerator,
        progress: TechProgress,
        max_attempts: int = 4,
        execution_timeout: float = 180.0,
        validate_candidates: bool = True,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if execution_timeout <= 0:
            raise ValueError("execution_timeout must be positive")
        self._context = context
        self._graph = graph
        self._scheduler = scheduler
        self._policy = policy
        self._library = library
        self._code_generator = code_generator
        self._progress = progress
        self._max_attempts = max_attempts
        self._execution_timeout = execution_timeout
        self._validate_candidates = validate_candidates
        self._verifier = TechEvidenceVerifier(graph)
        self._last_observation: GameBotObservation | None = None
        self._validation_feedback: list[str] = []

    @property
    def progress(self) -> TechProgress:
        return self._progress

    async def run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(0.1)

    async def _cancel_and_wait_until_idle(self, correlation_id: str) -> str | None:
        try:
            await self._context.runtime.cancel_action(correlation_id)
        except Exception as exc:
            return f"CANCEL_ERROR:{type(exc).__name__}:{exc}"

        for _ in range(50):
            try:
                health = await self._context.runtime.health()
            except Exception as exc:
                return f"HEALTH_ERROR:{type(exc).__name__}:{exc}"
            if not bool(health.get("busy", False)):
                return None
            await asyncio.sleep(0.1)
        return "CANCEL_TIMEOUT:runtime remained busy after cancellation"

    async def run_once(self) -> LearningOutcome:
        observation = self._last_observation
        if observation is None:
            observation = await self._context.runtime.observe(
                f"frontier-{uuid4().hex}"
            )
            self._last_observation = observation

        selection = self._scheduler.select(self._progress, observation)
        if selection.kind == "discovery":
            discovery = selection.discovery
            if discovery is not None and (
                discovery.capability in self._context.authorized_capabilities
            ):
                task_id = f"discovery-{uuid4().hex}"
                params = dict(discovery.params)
                if discovery.capability == "goto":
                    if observation.position is None:
                        return LearningOutcome(
                            status="discovery",
                            attempts=0,
                            discovery=discovery,
                        )
                    offset = min(discovery.radius, 32)
                    params = {
                        "x": observation.position.x + offset,
                        "y": observation.position.y,
                        "z": observation.position.z,
                        "search_radius": discovery.radius,
                        "time_budget_seconds": discovery.seconds,
                    }
                await self._context.runtime.execute_action(
                    discovery.capability,
                    params,
                    session_id=self._context.session_id,
                    task_id=task_id,
                    correlation_id=f"discovery-goto-{uuid4().hex}",
                    timeout=float(discovery.seconds),
                )
                self._last_observation = await self._context.runtime.observe(
                    f"discovery-after-{uuid4().hex}"
                )
            return LearningOutcome(
                status="discovery",
                attempts=1 if discovery is not None else 0,
                discovery=discovery,
            )

        node = selection.node
        if node is None:
            raise RuntimeError("technology selection did not contain a node")

        task_id = f"task-{node.id}-{uuid4().hex}"
        feedback: list[str] = []
        relevant = await self._library.search_skills(node.name, limit=3)
        source_report = None
        source_policy: PolicyReport | None = None
        source_code = ""

        for attempt in range(1, self._max_attempts + 1):
            before = self._last_observation
            if attempt > 1:
                before = await self._context.runtime.observe(f"before-{uuid4().hex}")
            source_code = await self._code_generator.generate(
                node=node,
                observation=before,
                feedback=feedback,
                relevant_skills=relevant,
            )
            source_policy = self._policy.validate_code(source_code, self._context.manifest)
            if not source_policy.allowed:
                feedback.append(
                    "POLICY_REJECTED: "
                    + ",".join(
                        f"{violation.code}:{violation.subject}"
                        for violation in source_policy.violations
                    )
                )
                continue

            correlation_id = f"eval-{uuid4().hex}"
            try:
                execution = await self._context.runtime.eval_skill(
                    source_code,
                    allowed_capabilities=sorted(source_policy.authorized_capabilities),
                    session_id=self._context.session_id,
                    task_id=task_id,
                    correlation_id=correlation_id,
                    timeout=self._execution_timeout,
                )
                after = await self._context.runtime.observe(f"after-{uuid4().hex}")
            except Exception as exc:
                feedback.append(f"RUNTIME_ERROR:{type(exc).__name__}:{exc}")
                cleanup_failure = await self._cancel_and_wait_until_idle(correlation_id)
                if cleanup_failure is not None:
                    feedback.append(cleanup_failure)
                self._last_observation = None
                continue
            self._last_observation = after
            execution_failure = _execution_failure(execution)
            if execution_failure:
                feedback.append(execution_failure)
                continue

            source_report = self._verifier.verify(
                node_id=node.id,
                progress=self._progress,
                receipts=execution.receipts,
                before=before,
                after=after,
                session_id=self._context.session_id,
                task_id=task_id,
                runtime_id=self._context.manifest.runtime_id,
            )
            if source_report.valid:
                if source_report.unlock_record is None:
                    raise RuntimeError("valid technology report lacks unlock record")
                self._progress = self._progress.commit(source_report.unlock_record)
                break
            feedback.append(
                "EVIDENCE_REJECTED: "
                + ",".join(failure.code for failure in source_report.failures)
            )
        else:
            self._scheduler.record_failure(node.id)
            return LearningOutcome(
                status="failed",
                node_id=node.id,
                attempts=self._max_attempts,
                feedback=tuple(feedback),
            )

        if source_report is None or source_policy is None:
            raise RuntimeError("learning source succeeded without policy/evidence reports")

        skill = self._build_candidate(
            node=node,
            code=source_code,
            task_id=task_id,
            policy=source_policy,
            evidence_refs=list(source_report.unlock_record.receipt_hashes),
        )
        await self._library.save_skill(skill)
        await self._context.repository.commit_checkpoint(
            VoyagerCheckpoint(
                session_id=self._context.session_id,
                task_id=task_id,
                observation_hash=source_report.unlock_record.final_observation_hash,
                unlocked_tech=self._progress.unlocked_nodes,
                metadata={"inventory": dict(self._last_observation.inventory)},
            )
        )

        if not self._validate_candidates:
            return LearningOutcome(
                status="candidate",
                node_id=node.id,
                skill_id=skill.id,
                attempts=attempt,
                feedback=tuple(feedback),
            )

        trusted = await self._validate_candidate(node, skill, source_policy)
        return LearningOutcome(
            status="trusted" if trusted else "candidate",
            node_id=node.id,
            skill_id=skill.id,
            attempts=attempt,
            feedback=tuple(feedback + self._validation_feedback),
        )

    def _build_candidate(
        self,
        *,
        node: TechNode,
        code: str,
        task_id: str,
        policy: PolicyReport,
        evidence_refs: list[str],
    ) -> Skill:
        return Skill(
            id=f"voyager-{node.id}-{uuid4().hex[:12]}",
            name=node.name,
            description=f"Evidence-backed candidate for {node.id}",
            body={"type": "code", "code": code, "api_version": "v1"},
            postconditions=[
                f"has_{item} >= {minimum}"
                for item, minimum in node.postconditions.items()
            ],
            tags=["voyager", node.id, "candidate"],
            is_learned=True,
            validated=False,
            trust_stage=SkillTrustStage.CANDIDATE,
            provenance=SkillProvenance(
                source_session_id=self._context.session_id,
                source_task_id=task_id,
                policy_report=policy.model_dump(mode="json"),
                evidence_refs=evidence_refs,
                environment_fingerprint=_environment_fingerprint(
                    self._context.manifest.runtime_id,
                    self._last_observation.environment,
                ),
            ),
            success_count=1,
        )

    async def _validate_candidate(
        self,
        node: TechNode,
        skill: Skill,
        policy: PolicyReport,
    ) -> bool:
        self._validation_feedback = []
        validation_task_id = f"validation-{node.id}-{uuid4().hex}"
        before = await self._context.runtime.observe(f"validation-before-{uuid4().hex}")
        correlation_id = f"validation-eval-{uuid4().hex}"
        try:
            execution = await self._context.runtime.eval_skill(
                skill.body["code"],
                allowed_capabilities=sorted(policy.authorized_capabilities),
                session_id=self._context.session_id,
                task_id=validation_task_id,
                correlation_id=correlation_id,
                timeout=self._execution_timeout,
            )
            after = await self._context.runtime.observe(f"validation-after-{uuid4().hex}")
        except Exception as exc:
            self._validation_feedback.append(
                f"RUNTIME_ERROR:{type(exc).__name__}:{exc}"
            )
            cleanup_failure = await self._cancel_and_wait_until_idle(correlation_id)
            if cleanup_failure is not None:
                self._validation_feedback.append(cleanup_failure)
            self._last_observation = None
            return False
        self._last_observation = after
        execution_failure = _execution_failure(execution)
        if execution_failure:
            self._validation_feedback.append(execution_failure)
            return False
        report = self._verifier.verify(
            node_id=node.id,
            progress=self._progress,
            receipts=execution.receipts,
            before=before,
            after=after,
            session_id=self._context.session_id,
            task_id=validation_task_id,
            runtime_id=self._context.manifest.runtime_id,
        )
        if not report.valid:
            self._validation_feedback.append(
                "EVIDENCE_REJECTED: "
                + ",".join(failure.code for failure in report.failures)
            )
            return False
        await self._context.repository.commit_checkpoint(
            VoyagerCheckpoint(
                session_id=self._context.session_id,
                task_id=validation_task_id,
                observation_hash=after.content_hash,
                unlocked_tech=self._progress.unlocked_nodes,
                metadata={"inventory": dict(after.inventory)},
            )
        )
        promoted = await self._library.promote_skill(
            skill.id,
            validation_session_id=validation_task_id,
            evidence_refs=[receipt.content_hash for receipt in execution.receipts],
            environment_fingerprint=_environment_fingerprint(
                self._context.manifest.runtime_id,
                after.environment,
            ),
        )
        if not promoted:
            self._validation_feedback.append("PROMOTION_REJECTED")
        return promoted
