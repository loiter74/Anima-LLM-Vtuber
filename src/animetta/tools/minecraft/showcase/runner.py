"""Natural-language-only runner for the adaptive Minecraft showcase."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.minecraft.mission.models import (
    MissionReport,
    MissionSpec,
    StageIO,
    StageMedia,
    VerificationPredicate,
    WalkthroughManifest,
)

from .presentation import REQUIRED_STAGE_IDS, PresentationManifest, PresentationWriter
from .scenario import (
    MissionStartBoundary,
    ScenarioPreparer,
    ScenarioReceipt,
    ScenarioSpec,
    default_showcase_scenario,
)
from .stage_projector import StageEvidenceFacts, StageProjector

SHOWCASE_USER_TEXT = (
    "请在这个新世界里分别与僵尸、骷髅和蜘蛛交互并确认击败结果，独自建好安全的入门小屋；"
    "然后在有限范围内自主探索，找到并获得一种我们还没记录的新物品，学习一个可复用的新技能并再次"
    "利用它获取资源，同时至少解锁两个 Minecraft 原版成就。全程注意安全，最后只根据真实证据向我总结。"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ViewerReadiness(_FrozenModel):
    username: str
    target: str
    authenticated: bool
    spectator: bool
    binding_state: Literal["following"]
    confirmed: Literal[True]
    capture_probe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _confirmed_gate(self) -> Self:
        if not self.authenticated or not self.spectator:
            raise ValueError("VIEWER_NOT_AUTHENTICATED_AND_FOLLOWING")
        if self.finished_at_ms < self.started_at_ms:
            raise ValueError("readiness finish precedes start")
        return self


class DialogueSubmission(_FrozenModel):
    exact_user_text: str = Field(min_length=1, max_length=4_000)
    visible_response: str = Field(max_length=4_000)
    tool_name: Literal["mc_execute"]
    tool_call_id: str = Field(min_length=1, max_length=256)
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    mission_payload: MissionSpec
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _mission_matches_submission(self) -> Self:
        if self.mission_payload.mission_id != self.mission_id:
            raise ValueError("dialogue mission ID mismatch")
        if self.finished_at_ms < self.started_at_ms:
            raise ValueError("dialogue finish precedes start")
        return self


class AdmittedDialogue(_FrozenModel):
    """One ordinary conversation turn whose real tool call crossed the boundary."""

    dialogue: DialogueSubmission
    mission_boundary: MissionStartBoundary

    @model_validator(mode="after")
    def _identity_matches(self) -> Self:
        if self.dialogue.mission_id != self.mission_boundary.mission_id:
            raise ValueError("admitted dialogue mission identity mismatch")
        return self


StageEvidence = StageEvidenceFacts


class ShowcaseEvidenceSnapshot(_FrozenModel):
    run_id: str
    mission_id: str
    proposals: tuple[dict[str, Any], ...] = ()
    commands: tuple[dict[str, Any], ...] = ()
    receipts: tuple[dict[str, Any], ...] = ()
    discoveries: tuple[dict[str, Any], ...] = ()
    skills: tuple[dict[str, Any], ...] = ()
    advancements: tuple[dict[str, Any], ...] = ()
    mission_report: MissionReport
    final_status: dict[str, Any]
    final_narration: str = Field(min_length=1, max_length=4_000)
    stages: tuple[StageEvidenceFacts, ...]

    @model_validator(mode="after")
    def _complete_current_run(self) -> Self:
        expected = REQUIRED_STAGE_IDS[4:]
        if tuple(stage.stage_id for stage in self.stages) != expected:
            raise ValueError("showcase evidence stages are incomplete or out of order")
        if self.mission_report.mission_id != self.mission_id:
            raise ValueError("mission report belongs to another mission")
        return self


@dataclass(frozen=True, slots=True)
class CapturedMedia:
    artifact_id: str
    kind: Literal["screenshot", "video"]
    content: bytes
    suffix: str
    captured_at_ms: int
    media_started_at_ms: int
    media_finished_at_ms: int
    stage_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaCaptureBundle:
    screenshots: tuple[CapturedMedia, ...]
    video: CapturedMedia


class ShowcaseBackend(Protocol):
    async def wait_for_readiness(
        self, *, run_id: str, scenario: ScenarioSpec
    ) -> ViewerReadiness: ...

    async def submit_user_text(
        self,
        *,
        run_id: str,
        user_text: str,
        start_mission: Callable[[str], MissionStartBoundary],
    ) -> AdmittedDialogue: ...

    async def wait_for_completion(
        self, *, run_id: str, mission_id: str
    ) -> ShowcaseEvidenceSnapshot: ...


class ShowcaseCapture(Protocol):
    async def start(self, *, run_id: str) -> None: ...

    async def collect(
        self, *, run_id: str, mission_id: str, stages: tuple[StageIO, ...]
    ) -> MediaCaptureBundle: ...

    async def abort(self) -> None: ...


class WalkthroughPublisher(Protocol):
    async def publish_walkthrough(
        self,
        walkthrough: WalkthroughManifest,
        *,
        projection_version: int,
        occurred_at_ms: int,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class ShowcaseRunResult:
    scenario: ScenarioSpec
    scenario_receipt: ScenarioReceipt
    mission_boundary: MissionStartBoundary
    dialogue: DialogueSubmission
    evidence: ShowcaseEvidenceSnapshot
    manifest: PresentationManifest


_STAGE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "combat": ("receipts",),
    "construction": ("receipts",),
    "autonomous-exploration": ("proposals", "commands"),
    "discovery-acquisition": ("discoveries", "receipts"),
    "skill-learning-validation": ("skills", "receipts"),
    "skill-reuse": ("skills", "receipts"),
    "progress-projection": ("advancements", "commands"),
    "final-summary": ("mission-report", "advancements", "final-status", "final-narration"),
}


class ShowcaseRunner:
    def __init__(
        self,
        *,
        scenario_preparer: ScenarioPreparer,
        backend: ShowcaseBackend,
        capture: ShowcaseCapture,
        output_root: Path,
        projection_publisher: WalkthroughPublisher | None = None,
    ) -> None:
        self._scenario_preparer = scenario_preparer
        self._backend = backend
        self._capture = capture
        self._output_root = output_root
        self._projection_publisher = projection_publisher

    async def run(self, *, run_id: str, user_text: str) -> ShowcaseRunResult:
        await self._capture.start(run_id=run_id)
        try:
            return await self._run_started(run_id=run_id, user_text=user_text)
        except BaseException:
            await self._capture.abort()
            raise

    async def _run_started(self, *, run_id: str, user_text: str) -> ShowcaseRunResult:
        scenario = default_showcase_scenario()
        receipt = await self._scenario_preparer.prepare(scenario, run_id=run_id)
        readiness = await self._backend.wait_for_readiness(run_id=run_id, scenario=scenario)
        if (
            readiness.username != scenario.viewer_username
            or readiness.target != scenario.bot_username
        ):
            raise RuntimeError("VIEWER_IDENTITY_MISMATCH")

        admitted = await self._backend.submit_user_text(
            run_id=run_id,
            user_text=user_text,
            start_mission=lambda mission_id: self._scenario_preparer.start_mission(
                receipt,
                mission_id=mission_id,
            ),
        )
        dialogue = admitted.dialogue
        if dialogue.exact_user_text != user_text:
            raise RuntimeError("DIALOGUE_INPUT_MISMATCH")
        boundary = admitted.mission_boundary
        if boundary.run_id != run_id or boundary.mission_id != dialogue.mission_id:
            raise RuntimeError("MISSION_BOUNDARY_IDENTITY_MISMATCH")
        evidence = await self._backend.wait_for_completion(
            run_id=run_id,
            mission_id=dialogue.mission_id,
        )
        if evidence.run_id != run_id or evidence.mission_id != dialogue.mission_id:
            raise RuntimeError("SHOWCASE_EVIDENCE_IDENTITY_MISMATCH")

        writer = PresentationWriter(
            output_root=self._output_root,
            run_id=run_id,
            mission_id=dialogue.mission_id,
            started_at_ms=receipt.started_at_ms,
        )
        writer.write_json_artifact(
            artifact_id="scenario-input",
            kind="scenario_input",
            payload=scenario.model_dump(mode="json"),
            created_at_ms=receipt.started_at_ms,
        )
        writer.write_json_artifact(
            artifact_id="scenario-receipt",
            kind="scenario_receipt",
            payload=receipt.model_dump(mode="json"),
            created_at_ms=receipt.finished_at_ms,
        )
        writer.write_json_artifact(
            artifact_id="readiness",
            kind="readiness",
            payload=readiness.model_dump(mode="json"),
            created_at_ms=readiness.finished_at_ms,
        )
        writer.write_json_artifact(
            artifact_id="dialogue",
            kind="dialogue",
            payload=dialogue.model_dump(mode="json"),
            created_at_ms=dialogue.finished_at_ms,
        )
        writer.write_json_artifact(
            artifact_id="mission",
            kind="mission",
            payload=dialogue.mission_payload.model_dump(mode="json"),
            created_at_ms=boundary.started_at_ms,
        )
        snapshot_artifacts = {
            "proposals": evidence.proposals,
            "commands": evidence.commands,
            "receipts": evidence.receipts,
            "discoveries": evidence.discoveries,
            "skills": evidence.skills,
            "advancements": evidence.advancements,
            "mission-report": evidence.mission_report.model_dump(mode="json"),
            "final-status": evidence.final_status,
            "final-narration": {"text": evidence.final_narration},
        }
        finished_at_ms = evidence.stages[-1].finished_at_ms
        if finished_at_ms is None:
            raise RuntimeError("SHOWCASE_FINAL_STAGE_NOT_TERMINAL")
        for artifact_id, payload in snapshot_artifacts.items():
            writer.write_json_artifact(
                artifact_id=artifact_id,
                kind=artifact_id.replace("-", "_"),  # type: ignore[arg-type]
                payload=payload,
                created_at_ms=finished_at_ms,
            )

        scenario_input_ref = writer.evidence_ref("scenario-input")
        scenario_receipt_ref = writer.evidence_ref("scenario-receipt")
        readiness_ref = writer.evidence_ref("readiness")
        dialogue_input_ref = writer.evidence_ref("dialogue", json_pointer="/exact_user_text")
        dialogue_output_ref = writer.evidence_ref("dialogue", json_pointer="/mission_payload")
        mission_ref = writer.evidence_ref("mission")
        budget_ref = writer.evidence_ref("mission", json_pointer="/parent_budget")
        facts: list[StageEvidenceFacts] = [
            StageEvidenceFacts(
                stage_id="scenario-setup",
                lifecycle="passed",
                started_at_ms=receipt.started_at_ms,
                finished_at_ms=receipt.finished_at_ms,
                input_refs=(scenario_input_ref,),
                decision_source="scenario-preparer",
                reason_code="SCENARIO_READY",
                output_refs=(scenario_receipt_ref,),
                verifier="ScenarioReceiptVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id="scenario-ready",
                        expected={"all_operations": "success"},
                        actual={"operation_count": len(receipt.operations)},
                        status="pass",
                    ),
                ),
                evidence_refs=(scenario_receipt_ref,),
            ),
            StageEvidenceFacts(
                stage_id="capture-readiness",
                lifecycle="passed",
                started_at_ms=readiness.started_at_ms,
                finished_at_ms=readiness.finished_at_ms,
                input_refs=(scenario_input_ref,),
                decision_source="spectator-attachment",
                reason_code="VIEWER_FOLLOWING_CONFIRMED",
                output_refs=(readiness_ref,),
                verifier="ViewerReadinessVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id="viewer-following",
                        expected={"authenticated": True, "binding_state": "following"},
                        actual={
                            "authenticated": readiness.authenticated,
                            "binding_state": readiness.binding_state,
                        },
                        status="pass",
                    ),
                ),
                evidence_refs=(readiness_ref,),
            ),
            StageEvidenceFacts(
                stage_id="dialogue",
                lifecycle="passed",
                started_at_ms=dialogue.started_at_ms,
                finished_at_ms=dialogue.finished_at_ms,
                input_refs=(dialogue_input_ref,),
                decision_source="configured-model",
                reason_code="MISSION_TOOL_CALL_EMITTED",
                selected_capability="mc_execute",
                output_refs=(dialogue_output_ref,),
                verifier="DialogueSemanticVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id="exactly-one-mc-execute",
                        expected={"tool_name": "mc_execute", "count": 1},
                        actual={"tool_name": dialogue.tool_name, "count": 1},
                        status="pass",
                    ),
                ),
                evidence_refs=(dialogue_output_ref,),
            ),
            StageEvidenceFacts(
                stage_id="mission-admission",
                lifecycle="passed",
                started_at_ms=dialogue.finished_at_ms,
                finished_at_ms=max(dialogue.finished_at_ms, boundary.started_at_ms),
                input_refs=(dialogue_output_ref,),
                decision_source="goal-admission",
                reason_code="ADMITTED",
                budget_ref=budget_ref,
                output_refs=(mission_ref,),
                verifier="MissionAdmissionVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id="mission-identity",
                        expected={"mission_id": dialogue.mission_id},
                        actual={"mission_id": dialogue.mission_payload.mission_id},
                        status="pass",
                    ),
                ),
                evidence_refs=(mission_ref,),
            ),
        ]
        for item in evidence.stages:
            artifact_ids = _STAGE_ARTIFACTS[item.stage_id]
            output_refs = (writer.evidence_ref(artifact_ids[0]),)
            evidence_refs = tuple(writer.evidence_ref(artifact_id) for artifact_id in artifact_ids)
            checkpoints = tuple(
                checkpoint.model_copy(
                    update={
                        "input_refs": (mission_ref,),
                        "output_refs": output_refs,
                        "evidence_refs": evidence_refs,
                    }
                )
                for checkpoint in item.checkpoints
            )
            facts.append(
                StageEvidenceFacts(
                    stage_id=item.stage_id,
                    lifecycle=item.lifecycle,
                    started_at_ms=item.started_at_ms,
                    finished_at_ms=item.finished_at_ms,
                    input_refs=(mission_ref,),
                    decision_source=item.decision_source,
                    reason_code=item.reason_code,
                    selected_strategy=item.selected_strategy,
                    selected_capability=item.selected_capability,
                    budget_ref=budget_ref,
                    output_refs=output_refs,
                    state_deltas=item.state_deltas,
                    verifier=item.verifier,
                    predicates=item.predicates,
                    checkpoints=checkpoints,
                    evidence_refs=evidence_refs,
                    failure=item.failure,
                )
            )

        projector = StageProjector()
        pre_capture_walkthrough = projector.project(
            run_id=run_id,
            mission_id=dialogue.mission_id,
            facts=tuple(facts),
        )
        if self._projection_publisher is not None:
            await self._projection_publisher.publish_walkthrough(
                pre_capture_walkthrough,
                projection_version=1,
                occurred_at_ms=finished_at_ms,
            )

        media = await self._capture.collect(
            run_id=run_id,
            mission_id=dialogue.mission_id,
            stages=pre_capture_walkthrough.stages,
        )
        screenshot_artifacts = []
        for captured in (*media.screenshots, media.video):
            artifact = writer.write_media_artifact(
                artifact_id=captured.artifact_id,
                kind=captured.kind,
                content=captured.content,
                suffix=captured.suffix,
                captured_at_ms=captured.captured_at_ms,
                media_started_at_ms=captured.media_started_at_ms,
                media_finished_at_ms=captured.media_finished_at_ms,
                stage_ids=captured.stage_ids,
            )
            if captured.kind == "screenshot":
                screenshot_artifacts.append(artifact)
        media_by_stage: dict[str, list[StageMedia]] = {
            stage_id: [] for stage_id in REQUIRED_STAGE_IDS
        }
        for artifact in screenshot_artifacts:
            assert artifact.captured_at_ms is not None
            media_ref = writer.evidence_ref(artifact.artifact_id)
            for stage_id in artifact.stage_ids:
                media_by_stage[stage_id].append(
                    StageMedia(
                        evidence_ref=media_ref,
                        captured_at_ms=artifact.captured_at_ms,
                    )
                )
        facts_with_media = tuple(
            item.model_copy(update={"media": tuple(media_by_stage[item.stage_id])})
            for item in facts
        )
        walkthrough = projector.project(
            run_id=run_id,
            mission_id=dialogue.mission_id,
            facts=facts_with_media,
        )
        if self._projection_publisher is not None:
            await self._projection_publisher.publish_walkthrough(
                walkthrough,
                projection_version=2,
                occurred_at_ms=finished_at_ms,
            )
        writer.write_json_artifact(
            artifact_id="stage-io",
            kind="stage_io",
            payload=[stage.model_dump(mode="json") for stage in walkthrough.stages],
            created_at_ms=finished_at_ms,
        )
        manifest = writer.finalize(
            walkthrough=walkthrough,
            finished_at_ms=finished_at_ms,
        )
        return ShowcaseRunResult(
            scenario=scenario,
            scenario_receipt=receipt,
            mission_boundary=boundary,
            dialogue=dialogue,
            evidence=evidence,
            manifest=manifest,
        )
