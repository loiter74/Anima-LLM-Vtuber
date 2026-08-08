from __future__ import annotations

import json

import pytest

from animetta.tools.minecraft.mission import CheckpointIO, StageMedia, VerificationPredicate
from animetta.tools.minecraft.showcase.presentation import (
    REQUIRED_JSON_ARTIFACT_KINDS,
    REQUIRED_STAGE_IDS,
    PresentationValidationError,
    PresentationWriter,
)
from animetta.tools.minecraft.showcase.stage_projector import (
    SHOWCASE_STAGE_DEFINITIONS,
    StageEvidenceFacts,
    StageProjector,
)


def _complete_writer(tmp_path, *, fail_final: bool = False):
    writer = PresentationWriter(
        output_root=tmp_path,
        run_id="showcase-run-001",
        mission_id="adaptive-showcase-001",
        started_at_ms=1_000,
    )
    for kind in REQUIRED_JSON_ARTIFACT_KINDS:
        if kind == "stage_io":
            continue
        writer.write_json_artifact(
            artifact_id=kind.replace("_", "-"),
            kind=kind,
            payload={"kind": kind, "run_id": "showcase-run-001"},
            created_at_ms=1_000,
        )

    stage_times: dict[str, tuple[int, int, int]] = {}
    for definition in SHOWCASE_STAGE_DEFINITIONS:
        started = 1_000 + (definition.ordinal - 1) * 1_000
        finished = started + 900
        captured = started + 450
        stage_times[definition.stage_id] = (started, finished, captured)
        writer.write_media_artifact(
            artifact_id=f"screenshot-{definition.ordinal:02d}",
            kind="screenshot",
            content=b"fresh-png-evidence",
            suffix=".png",
            captured_at_ms=captured,
            media_started_at_ms=captured,
            media_finished_at_ms=captured,
            stage_ids=(definition.stage_id,),
        )
    finished_at_ms = stage_times[REQUIRED_STAGE_IDS[-1]][1]
    writer.write_media_artifact(
        artifact_id="full-run-video",
        kind="video",
        content=b"fresh-video-evidence",
        suffix=".webm",
        captured_at_ms=1_000,
        media_started_at_ms=1_000,
        media_finished_at_ms=finished_at_ms,
        stage_ids=REQUIRED_STAGE_IDS,
    )

    input_ref = writer.evidence_ref("scenario-input")
    output_ref = writer.evidence_ref("mission-report")
    evidence_ref = writer.evidence_ref("receipts")
    facts = []
    for definition in SHOWCASE_STAGE_DEFINITIONS:
        started, finished, captured = stage_times[definition.stage_id]
        failed = fail_final and definition.stage_id == "final-summary"
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
                evidence_refs=(evidence_ref,),
            )
            for checkpoint_id in definition.checkpoint_ids
        )
        facts.append(
            StageEvidenceFacts(
                stage_id=definition.stage_id,
                lifecycle="failed" if failed else "passed",
                started_at_ms=started,
                finished_at_ms=finished,
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
                evidence_refs=(evidence_ref,),
                media=(
                    StageMedia(
                        evidence_ref=writer.evidence_ref(f"screenshot-{definition.ordinal:02d}"),
                        captured_at_ms=captured,
                    ),
                ),
                failure=(
                    {
                        "code": "EVIDENCE_ONLY_SUMMARY_FAILED",
                        "layer": "presentation",
                        "retryable": False,
                        "operator_action": "inspect final narration evidence",
                    }
                    if failed
                    else None
                ),
            )
        )
    walkthrough = StageProjector().project(
        run_id=writer.run_id,
        mission_id=writer.mission_id,
        facts=tuple(facts),
    )
    writer.write_json_artifact(
        artifact_id="stage-io",
        kind="stage_io",
        payload=[stage.model_dump(mode="json") for stage in walkthrough.stages],
        created_at_ms=finished_at_ms,
    )
    return writer, walkthrough, finished_at_ms


def test_complete_bundle_has_current_ids_hashes_stages_and_full_video(tmp_path) -> None:
    writer, walkthrough, finished_at_ms = _complete_writer(tmp_path)

    manifest = writer.finalize(walkthrough=walkthrough, finished_at_ms=finished_at_ms)

    assert manifest.run_id == "showcase-run-001"
    assert manifest.mission_id == "adaptive-showcase-001"
    assert tuple(stage.stage_id for stage in manifest.stages) == REQUIRED_STAGE_IDS
    assert manifest.projection_hash == walkthrough.projection_hash
    assert manifest.bundle_valid is True
    assert manifest.acceptance_passed is True
    assert all(artifact.sha256 for artifact in manifest.artifacts)
    stored = json.loads((writer.run_root / "manifest.json").read_text(encoding="utf-8"))
    assert stored["manifest_hash"] == manifest.manifest_hash


def test_valid_diagnostic_bundle_can_publish_failed_acceptance(tmp_path) -> None:
    writer, walkthrough, finished_at_ms = _complete_writer(tmp_path, fail_final=True)

    manifest = writer.finalize(walkthrough=walkthrough, finished_at_ms=finished_at_ms)

    assert manifest.bundle_valid is True
    assert manifest.acceptance_passed is False


def test_bundle_rejects_missing_stage_or_missing_stage_io_refs(tmp_path) -> None:
    writer, walkthrough, finished_at_ms = _complete_writer(tmp_path)
    missing = walkthrough.model_copy(update={"stages": walkthrough.stages[:-1]})

    with pytest.raises(PresentationValidationError, match="MISSING_REQUIRED_STAGE"):
        writer.finalize(walkthrough=missing, finished_at_ms=finished_at_ms)

    stage = walkthrough.stages[0].model_copy(update={"evidence_refs": ()})
    incomplete = walkthrough.model_copy(update={"stages": (stage, *walkthrough.stages[1:])})
    with pytest.raises(PresentationValidationError, match="STAGE_IO_INCOMPLETE"):
        writer.finalize(walkthrough=incomplete, finished_at_ms=finished_at_ms)


def test_bundle_rejects_stale_capture_and_incomplete_video_coverage(tmp_path) -> None:
    writer, walkthrough, finished_at_ms = _complete_writer(tmp_path)
    writer._artifacts = [
        artifact.model_copy(update={"captured_at_ms": 999})
        if artifact.kind == "screenshot"
        else artifact.model_copy(update={"media_finished_at_ms": finished_at_ms - 1_000})
        if artifact.kind == "video"
        else artifact
        for artifact in writer._artifacts
    ]

    with pytest.raises(
        PresentationValidationError,
        match="STAGE_MEDIA_REF_INVALID|STALE_MEDIA|VIDEO_COVERAGE",
    ):
        writer.finalize(walkthrough=walkthrough, finished_at_ms=finished_at_ms)


@pytest.mark.parametrize(
    "payload",
    [
        {"authorization": "Bearer secret-token"},
        {"api_key": "sk-sensitive"},
        {"path": r"C:\Users\someone\private\capture.png"},
        {"path": "/home/someone/private/capture.png"},
    ],
)
def test_writer_rejects_secrets_and_unrestricted_absolute_paths(tmp_path, payload) -> None:
    writer = PresentationWriter(
        output_root=tmp_path,
        run_id="showcase-run-unsafe",
        mission_id="adaptive-showcase-unsafe",
        started_at_ms=1_000,
    )

    with pytest.raises(PresentationValidationError, match="UNSAFE_ARTIFACT"):
        writer.write_json_artifact(
            artifact_id="unsafe",
            kind="dialogue",
            payload=payload,
            created_at_ms=1_100,
        )
