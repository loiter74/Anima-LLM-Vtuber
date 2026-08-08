from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.mission.models import (
    CheckpointIO,
    MissionReport,
    VerificationPredicate,
)
from animetta.tools.minecraft.showcase.runner import (
    SHOWCASE_USER_TEXT,
    AdmittedDialogue,
    CapturedMedia,
    DialogueSubmission,
    MediaCaptureBundle,
    ShowcaseEvidenceSnapshot,
    ShowcaseRunner,
    StageEvidence,
    ViewerReadiness,
)
from animetta.tools.minecraft.showcase.scenario import (
    ScenarioPreparer,
    SetupExecutionResult,
    compile_setup_operations,
)
from tests.tools.minecraft.mission.test_coordinator import _fixed_mission


def test_python_start_gate_rejects_spectator_mode_without_following_confirmation() -> None:
    with pytest.raises(ValidationError):
        ViewerReadiness.model_validate(
            {
                "username": "LUN077",
                "target": "AnimettaBot",
                "authenticated": True,
                "spectator": True,
                "binding_state": "attaching",
                "confirmed": False,
                "capture_probe_sha256": "a" * 64,
                "started_at_ms": 1_000,
                "finished_at_ms": 1_900,
            }
        )


class _Executor:
    def __init__(self) -> None:
        self.operations = []

    async def execute(self, operation):
        self.operations.append(operation)
        return SetupExecutionResult(
            operation_id=operation.operation_id,
            outcome="success",
            response_code="OK",
        )


class _Environment:
    async def prepare_disposable_world(self, scenario, run_id):
        return "world/server.properties"

    async def create_clean_stores(self, run_id, store_names):
        return tuple(f"stores/{name}.sqlite3" for name in store_names)


class _Backend:
    def __init__(self) -> None:
        self.calls = []

    async def wait_for_readiness(self, *, run_id, scenario):
        self.calls.append(("readiness", run_id, scenario.scenario_id))
        return ViewerReadiness(
            username="LUN077",
            target="AnimettaBot",
            authenticated=True,
            spectator=True,
            binding_state="following",
            confirmed=True,
            capture_probe_sha256="a" * 64,
            started_at_ms=1_000,
            finished_at_ms=1_900,
        )

    async def submit_user_text(self, *, run_id, user_text, start_mission):
        self.calls.append(("dialogue", run_id, user_text))
        dialogue = DialogueSubmission(
            exact_user_text=user_text,
            visible_response="好，我会按证据执行。",
            tool_name="mc_execute",
            tool_call_id="call-real-model-001",
            mission_id="adaptive-showcase-001",
            mission_payload=_fixed_mission().model_copy(
                update={"mission_id": "adaptive-showcase-001"}
            ),
            started_at_ms=2_000,
            finished_at_ms=2_900,
        )
        self.calls.append(("before-mc-execute", run_id, dialogue.mission_id))
        boundary = start_mission(dialogue.mission_id)
        self.calls.append(("mc-execute", run_id, dialogue.mission_id))
        return AdmittedDialogue(dialogue=dialogue, mission_boundary=boundary)

    async def wait_for_completion(self, *, run_id, mission_id):
        self.calls.append(("completion", run_id, mission_id))
        stage_ids = (
            "combat",
            "construction",
            "autonomous-exploration",
            "discovery-acquisition",
            "skill-learning-validation",
            "skill-reuse",
            "progress-projection",
            "final-summary",
        )
        checkpoint_ids = {
            "combat": ("zombie", "skeleton", "spider"),
            "construction": (
                "blueprint-selected",
                "placements-executed",
                "region-verified",
            ),
            "skill-learning-validation": ("source-a-learning", "source-b-validation"),
            "skill-reuse": ("source-c-reuse",),
        }
        spans = tuple(
            StageEvidence(
                stage_id=stage_id,
                lifecycle="passed",
                started_at_ms=4_000 + index * 1_000,
                finished_at_ms=4_900 + index * 1_000,
                decision_source="voyager-controller",
                reason_code="VERIFIED",
                verifier="TypedVerifier",
                predicates=(
                    VerificationPredicate(
                        predicate_id=f"{stage_id}-verified",
                        expected=True,
                        actual=True,
                        status="pass",
                    ),
                ),
                checkpoints=tuple(
                    CheckpointIO(
                        checkpoint_id=checkpoint_id,
                        label=checkpoint_id,
                        lifecycle="passed",
                        decision_source="voyager-controller",
                        reason_code="VERIFIED",
                        verifier="TypedVerifier",
                        predicates=(
                            VerificationPredicate(
                                predicate_id=f"{checkpoint_id}-verified",
                                expected=True,
                                actual=True,
                                status="pass",
                            ),
                        ),
                    )
                    for checkpoint_id in checkpoint_ids.get(stage_id, ())
                ),
            )
            for index, stage_id in enumerate(stage_ids)
        )
        return ShowcaseEvidenceSnapshot(
            run_id=run_id,
            mission_id=mission_id,
            proposals=[{"proposal_id": "proposal-1"}],
            commands=[{"command_id": "command-1"}],
            receipts=[{"receipt_id": "receipt-1"}],
            discoveries=[{"fact_id": "copper"}],
            skills=[{"skill_id": "acquire-copper", "reused": True}],
            advancements=[{"advancement_id": "minecraft:story/mine_stone"}],
            mission_report=MissionReport(
                mission_id=mission_id,
                status="completed",
                evidence_refs=("receipt-1",),
            ),
            final_status={"status": "completed"},
            final_narration="任务已根据已提交证据完成。",
            stages=spans,
        )


class _Capture:
    async def start(self, *, run_id):
        self.run_id = run_id

    async def abort(self):
        return None

    async def collect(self, *, run_id, mission_id, stages):
        assert all(
            stage.started_at_ms is not None and stage.finished_at_ms is not None for stage in stages
        )
        screenshots = tuple(
            CapturedMedia(
                artifact_id=f"capture-{index:02d}",
                kind="screenshot",
                content=b"fresh screenshot",
                suffix=".png",
                captured_at_ms=(stage.started_at_ms + stage.finished_at_ms) // 2,
                media_started_at_ms=(stage.started_at_ms + stage.finished_at_ms) // 2,
                media_finished_at_ms=(stage.started_at_ms + stage.finished_at_ms) // 2,
                stage_ids=(stage.stage_id,),
            )
            for index, stage in enumerate(stages, start=1)
        )
        return MediaCaptureBundle(
            screenshots=screenshots,
            video=CapturedMedia(
                artifact_id="complete-run-video",
                kind="video",
                content=b"fresh full video",
                suffix=".webm",
                captured_at_ms=stages[0].started_at_ms,
                media_started_at_ms=stages[0].started_at_ms,
                media_finished_at_ms=stages[-1].finished_at_ms,
                stage_ids=tuple(stage.stage_id for stage in stages),
            ),
        )


class _Publisher:
    def __init__(self) -> None:
        self.walkthroughs = []

    async def publish_walkthrough(self, walkthrough, *, projection_version, occurred_at_ms):
        self.walkthroughs.append((walkthrough, projection_version, occurred_at_ms))
        return len(walkthrough.stages)


async def test_runner_uses_only_natural_language_then_packages_all_evidence(tmp_path) -> None:
    executor = _Executor()
    backend = _Backend()
    scenario_clock = iter([100, *range(110, 200), 500, 3_000])
    preparer = ScenarioPreparer(
        executor=executor,
        environment=_Environment(),
        now_ms=scenario_clock.__next__,
    )
    publisher = _Publisher()
    runner = ShowcaseRunner(
        scenario_preparer=preparer,
        backend=backend,
        capture=_Capture(),
        output_root=tmp_path,
        projection_publisher=publisher,
    )

    result = await runner.run(run_id="showcase-run-001", user_text=SHOWCASE_USER_TEXT)

    assert [call[0] for call in backend.calls] == [
        "readiness",
        "dialogue",
        "before-mc-execute",
        "mc-execute",
        "completion",
    ]
    assert backend.calls[1][2] == SHOWCASE_USER_TEXT
    assert backend.calls[2][2] == "adaptive-showcase-001"
    assert backend.calls[3][2] == "adaptive-showcase-001"
    assert backend.calls[4][2] == "adaptive-showcase-001"
    assert len(executor.operations) == len(compile_setup_operations(result.scenario))
    assert preparer.state == "mission_started"
    assert result.manifest.mission_id == "adaptive-showcase-001"
    assert result.manifest.bundle_valid is True
    assert result.manifest.acceptance_passed is True
    assert len(result.manifest.stages) == 12
    assert [item[1] for item in publisher.walkthroughs] == [1, 2]
    assert publisher.walkthroughs[-1][0].projection_hash == result.manifest.projection_hash
    assert {artifact.kind for artifact in result.manifest.artifacts} >= {
        "scenario_input",
        "scenario_receipt",
        "dialogue",
        "mission",
        "proposals",
        "commands",
        "receipts",
        "discoveries",
        "skills",
        "advancements",
        "mission_report",
        "final_status",
        "final_narration",
        "stage_io",
        "screenshot",
        "video",
    }


async def test_runner_starts_boundary_inside_ordinary_mc_execute_call(tmp_path) -> None:
    """Scenario setup closes immediately before the conversation tool mutates the world."""

    executor = _Executor()
    backend = _Backend()
    scenario_clock = iter([100, *range(110, 200), 500, 3_000])
    preparer = ScenarioPreparer(
        executor=executor,
        environment=_Environment(),
        now_ms=scenario_clock.__next__,
    )
    runner = ShowcaseRunner(
        scenario_preparer=preparer,
        backend=backend,
        capture=_Capture(),
        output_root=tmp_path,
    )

    result = await runner.run(run_id="showcase-run-boundary", user_text=SHOWCASE_USER_TEXT)

    assert result.mission_boundary.mission_id == result.dialogue.mission_id
    assert [call[0] for call in backend.calls[:4]] == [
        "readiness",
        "dialogue",
        "before-mc-execute",
        "mc-execute",
    ]
