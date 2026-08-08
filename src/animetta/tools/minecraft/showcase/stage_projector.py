"""Pure read-only projection from durable showcase facts to StageIO v2."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.mission import (
    CheckpointIO,
    EvidenceRef,
    StageDefinition,
    StageFailure,
    StageIO,
    StageMedia,
    StageStateDelta,
    VerificationPredicate,
    WalkthroughManifest,
)

SHOWCASE_STAGE_DEFINITIONS: tuple[StageDefinition, ...] = (
    StageDefinition(
        stage_id="scenario-setup",
        ordinal=1,
        gameplay_evidence_eligible=False,
    ),
    StageDefinition(stage_id="capture-readiness", ordinal=2),
    StageDefinition(stage_id="dialogue", ordinal=3),
    StageDefinition(stage_id="mission-admission", ordinal=4),
    StageDefinition(
        stage_id="combat",
        ordinal=5,
        checkpoint_ids=("zombie", "skeleton", "spider"),
    ),
    StageDefinition(
        stage_id="construction",
        ordinal=6,
        checkpoint_ids=("blueprint-selected", "placements-executed", "region-verified"),
    ),
    StageDefinition(stage_id="autonomous-exploration", ordinal=7),
    StageDefinition(stage_id="discovery-acquisition", ordinal=8),
    StageDefinition(
        stage_id="skill-learning-validation",
        ordinal=9,
        checkpoint_ids=("source-a-learning", "source-b-validation"),
    ),
    StageDefinition(
        stage_id="skill-reuse",
        ordinal=10,
        checkpoint_ids=("source-c-reuse",),
    ),
    StageDefinition(stage_id="progress-projection", ordinal=11),
    StageDefinition(stage_id="final-summary", ordinal=12),
)


class StageEvidenceFacts(BaseModel):
    """Durable facts already owned by mission/evidence stores for one stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    lifecycle: Literal["pending", "running", "passed", "failed", "blocked", "skipped"]
    started_at_ms: int | None = Field(default=None, ge=0)
    finished_at_ms: int | None = Field(default=None, ge=0)
    input_refs: tuple[EvidenceRef, ...] = ()
    decision_source: str | None = Field(default=None, min_length=1, max_length=128)
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    selected_strategy: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,127}$")
    selected_capability: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    budget_ref: EvidenceRef | None = None
    output_refs: tuple[EvidenceRef, ...] = ()
    state_deltas: tuple[StageStateDelta, ...] = ()
    verifier: str | None = Field(default=None, min_length=1, max_length=128)
    predicates: tuple[VerificationPredicate, ...] = ()
    checkpoints: tuple[CheckpointIO, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    media: tuple[StageMedia, ...] = ()
    failure: StageFailure | None = None


def _sorted_refs(refs: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    return tuple(
        sorted(
            refs,
            key=lambda item: (
                item.artifact_id,
                item.artifact_kind,
                item.json_pointer,
                item.content_hash,
            ),
        )
    )


class StageProjector:
    """Build deterministic live/final stage views without mutation authority."""

    @staticmethod
    def _bundle_valid(
        stages: tuple[StageIO, ...], definitions: tuple[StageDefinition, ...]
    ) -> bool:
        by_id = {stage.stage_id: stage for stage in stages}
        for definition in definitions:
            if not definition.required:
                continue
            stage = by_id[definition.stage_id]
            if stage.lifecycle not in {"passed", "failed", "blocked"}:
                return False
            if not stage.input_refs or not stage.output_refs or not stage.evidence_refs:
                return False
            if stage.verifier is None or not stage.predicates:
                return False
            if not stage.media:
                return False
            checkpoints = {checkpoint.checkpoint_id: checkpoint for checkpoint in stage.checkpoints}
            if not set(definition.checkpoint_ids).issubset(checkpoints):
                return False
            for checkpoint_id in definition.checkpoint_ids:
                checkpoint = checkpoints[checkpoint_id]
                if checkpoint.lifecycle not in {"passed", "failed", "blocked"}:
                    return False
                if (
                    not checkpoint.input_refs
                    or not checkpoint.output_refs
                    or not checkpoint.evidence_refs
                    or checkpoint.verifier is None
                    or not checkpoint.predicates
                ):
                    return False
        return True

    @staticmethod
    def _acceptance_passed(
        stages: tuple[StageIO, ...],
        definitions: tuple[StageDefinition, ...],
        bundle_valid: bool,
    ) -> bool:
        if not bundle_valid:
            return False
        by_id = {stage.stage_id: stage for stage in stages}
        for definition in definitions:
            if not definition.required:
                continue
            stage = by_id[definition.stage_id]
            if stage.lifecycle != "passed":
                return False
            if any(predicate.status != "pass" for predicate in stage.predicates):
                return False
            checkpoints = {checkpoint.checkpoint_id: checkpoint for checkpoint in stage.checkpoints}
            if any(
                checkpoints[checkpoint_id].lifecycle != "passed"
                or any(
                    predicate.status != "pass"
                    for predicate in checkpoints[checkpoint_id].predicates
                )
                for checkpoint_id in definition.checkpoint_ids
            ):
                return False
        return True

    def project(
        self,
        *,
        run_id: str,
        mission_id: str,
        facts: tuple[StageEvidenceFacts, ...],
    ) -> WalkthroughManifest:
        fact_by_stage: dict[str, StageEvidenceFacts] = {}
        known_stage_ids = {definition.stage_id for definition in SHOWCASE_STAGE_DEFINITIONS}
        for item in facts:
            if item.stage_id not in known_stage_ids:
                raise ValueError(f"UNKNOWN_SHOWCASE_STAGE:{item.stage_id}")
            if item.stage_id in fact_by_stage:
                raise ValueError(f"DUPLICATE_SHOWCASE_STAGE_FACTS:{item.stage_id}")
            fact_by_stage[item.stage_id] = item

        stages: list[StageIO] = []
        for definition in SHOWCASE_STAGE_DEFINITIONS:
            item = fact_by_stage.get(definition.stage_id)
            if item is None:
                stages.append(
                    StageIO(
                        run_id=run_id,
                        mission_id=mission_id,
                        stage_id=definition.stage_id,
                        ordinal=definition.ordinal,
                        gameplay_evidence_eligible=definition.gameplay_evidence_eligible,
                        lifecycle="pending",
                    )
                )
                continue
            stages.append(
                StageIO(
                    run_id=run_id,
                    mission_id=mission_id,
                    stage_id=definition.stage_id,
                    ordinal=definition.ordinal,
                    gameplay_evidence_eligible=definition.gameplay_evidence_eligible,
                    lifecycle=item.lifecycle,
                    started_at_ms=item.started_at_ms,
                    finished_at_ms=item.finished_at_ms,
                    input_refs=_sorted_refs(item.input_refs),
                    decision_source=item.decision_source,
                    reason_code=item.reason_code,
                    selected_strategy=item.selected_strategy,
                    selected_capability=item.selected_capability,
                    budget_ref=item.budget_ref,
                    output_refs=_sorted_refs(item.output_refs),
                    state_deltas=item.state_deltas,
                    verifier=item.verifier,
                    predicates=item.predicates,
                    checkpoints=item.checkpoints,
                    evidence_refs=_sorted_refs(item.evidence_refs),
                    media=tuple(sorted(item.media, key=lambda media: media.captured_at_ms)),
                    failure=item.failure,
                )
            )
        stage_tuple = tuple(stages)
        bundle_valid = self._bundle_valid(stage_tuple, SHOWCASE_STAGE_DEFINITIONS)
        acceptance_passed = self._acceptance_passed(
            stage_tuple,
            SHOWCASE_STAGE_DEFINITIONS,
            bundle_valid,
        )
        projection_hash = canonical_json_hash(
            {
                "run_id": run_id,
                "mission_id": mission_id,
                "stage_definitions": [
                    definition.model_dump(mode="json") for definition in SHOWCASE_STAGE_DEFINITIONS
                ],
                "stages": [stage.model_dump(mode="json") for stage in stage_tuple],
                "bundle_valid": bundle_valid,
                "acceptance_passed": acceptance_passed,
            }
        )
        return WalkthroughManifest(
            run_id=run_id,
            mission_id=mission_id,
            projection_hash=projection_hash,
            stages=stage_tuple,
            bundle_valid=bundle_valid,
            acceptance_passed=acceptance_passed,
        )
