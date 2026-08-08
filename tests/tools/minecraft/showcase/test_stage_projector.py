from __future__ import annotations

import inspect
from hashlib import sha256

from animetta.tools.minecraft.mission import (
    CheckpointIO,
    EvidenceRef,
    StageFailure,
    StageMedia,
    VerificationPredicate,
)
from animetta.tools.minecraft.showcase.stage_projector import (
    SHOWCASE_STAGE_DEFINITIONS,
    StageEvidenceFacts,
    StageProjector,
)


def _ref(artifact_id: str, artifact_kind: str) -> EvidenceRef:
    return EvidenceRef(
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        json_pointer="/",
        content_hash=sha256(artifact_id.encode("utf-8")).hexdigest(),
    )


def _facts(*, fail_final: bool = False) -> tuple[StageEvidenceFacts, ...]:
    rows: list[StageEvidenceFacts] = []
    for definition in SHOWCASE_STAGE_DEFINITIONS:
        input_ref = _ref(f"input-{definition.ordinal:02d}", "stage_input")
        output_ref = _ref(f"output-{definition.ordinal:02d}", "stage_output")
        media_ref = _ref(f"media-{definition.ordinal:02d}", "screenshot")
        failed = fail_final and definition.stage_id == "final-summary"
        failure = (
            StageFailure(
                code="EVIDENCE_ONLY_SUMMARY_FAILED",
                layer="presentation",
                retryable=False,
                operator_action="inspect final narration evidence",
            )
            if failed
            else None
        )
        checkpoints = tuple(
            CheckpointIO(
                checkpoint_id=checkpoint_id,
                label=checkpoint_id,
                lifecycle="passed",
                input_refs=(input_ref,),
                decision_source="voyager-controller",
                reason_code="VERIFIED",
                output_refs=(output_ref,),
                verifier="TypedVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id=f"{checkpoint_id}-predicate",
                        expected=True,
                        actual=True,
                        status="pass",
                    ),
                ),
                evidence_refs=(output_ref,),
            )
            for checkpoint_id in definition.checkpoint_ids
        )
        rows.append(
            StageEvidenceFacts(
                stage_id=definition.stage_id,
                lifecycle="failed" if failed else "passed",
                started_at_ms=1_000 + definition.ordinal * 1_000,
                finished_at_ms=1_900 + definition.ordinal * 1_000,
                input_refs=(input_ref,),
                decision_source="voyager-controller",
                reason_code="FAILED" if failed else "VERIFIED",
                output_refs=(output_ref,),
                verifier="TypedVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id=f"{definition.stage_id}-predicate",
                        expected=True,
                        actual=not failed,
                        status="fail" if failed else "pass",
                    ),
                ),
                checkpoints=checkpoints,
                evidence_refs=(output_ref,),
                media=(
                    StageMedia(
                        evidence_ref=media_ref,
                        captured_at_ms=1_500 + definition.ordinal * 1_000,
                    ),
                ),
                failure=failure,
            )
        )
    return tuple(rows)


def test_projector_emits_exact_twelve_stage_catalog_and_setup_boundary() -> None:
    manifest = StageProjector().project(
        run_id="showcase-run-001",
        mission_id="adaptive-showcase-001",
        facts=_facts(),
    )

    assert tuple(stage.stage_id for stage in manifest.stages) == (
        "scenario-setup",
        "capture-readiness",
        "dialogue",
        "mission-admission",
        "combat",
        "construction",
        "autonomous-exploration",
        "discovery-acquisition",
        "skill-learning-validation",
        "skill-reuse",
        "progress-projection",
        "final-summary",
    )
    assert manifest.stages[0].gameplay_evidence_eligible is False
    assert all(stage.gameplay_evidence_eligible for stage in manifest.stages[1:])
    assert manifest.bundle_valid is True
    assert manifest.acceptance_passed is True


def test_projector_is_restart_deterministic_and_separates_bundle_from_acceptance() -> None:
    projector = StageProjector()
    facts = _facts(fail_final=True)

    first = projector.project(
        run_id="showcase-run-001",
        mission_id="adaptive-showcase-001",
        facts=facts,
    )
    replayed = tuple(
        StageEvidenceFacts.model_validate(item.model_dump(mode="json")) for item in reversed(facts)
    )
    second = projector.project(
        run_id="showcase-run-001",
        mission_id="adaptive-showcase-001",
        facts=replayed,
    )

    assert first.projection_hash == second.projection_hash
    assert first.stages == second.stages
    assert first.bundle_valid is True
    assert first.acceptance_passed is False


def test_missing_real_media_invalidates_bundle_without_synthesizing_timestamp() -> None:
    facts = list(_facts())
    facts[4] = facts[4].model_copy(update={"media": ()})

    manifest = StageProjector().project(
        run_id="showcase-run-001",
        mission_id="adaptive-showcase-001",
        facts=tuple(facts),
    )

    assert manifest.bundle_valid is False
    assert manifest.acceptance_passed is False
    assert manifest.stages[4].media == ()


def test_projector_has_no_mutation_dependency_or_command_submission_surface() -> None:
    module_source = inspect.getsource(inspect.getmodule(StageProjector))

    assert "journal" not in module_source
    assert "adapter" not in module_source
    assert "bridge" not in module_source
    assert "CommandExecutor" not in module_source
    assert set(vars(StageProjector)) <= {
        "__module__",
        "__doc__",
        "__dict__",
        "__weakref__",
        "__firstlineno__",
        "__static_attributes__",
        "project",
        "_bundle_valid",
        "_acceptance_passed",
    }
