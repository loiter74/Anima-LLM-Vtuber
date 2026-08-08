"""Run the complete real adaptive Minecraft showcase and package its evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from animetta.acceptance.minecraft_gameplay_review import (
    MinecraftReviewServerLease,
    resolve_external_runtime_dir,
)
from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import (
    MinecraftBotConfig,
    MinecraftClientViewerConfig,
    MinecraftConfig,
    MinecraftRuntimeConfig,
)
from animetta.tools.minecraft.mission.events import ProjectionEventPublisher
from animetta.tools.minecraft.showcase.live import (
    ConfiguredModelEvidenceNarrator,
    DesktopShowcaseCapture,
    LiveShowcaseBackend,
    ReviewRconSetupExecutor,
    ReviewScenarioEnvironment,
    configured_showcase_llm_from_environment,
    create_ordinary_showcase_submitter,
)
from animetta.tools.minecraft.showcase.projection_relay import ShowcaseProjectionServer
from animetta.tools.minecraft.showcase.promotion import (
    AcceptanceLedger,
    AcceptanceLedgerStore,
    RealAttempt,
)
from animetta.tools.minecraft.showcase.runner import (
    SHOWCASE_USER_TEXT,
    ShowcaseRunner,
    ShowcaseRunResult,
)
from animetta.tools.minecraft.showcase.scenario import (
    ScenarioPreparer,
    default_showcase_scenario,
)


class _MissionFeedbackWriter:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._sequence = 0

    async def __call__(self, mission_id: str, snapshot: object, elapsed: float) -> None:
        mission = getattr(snapshot, "mission")
        transitions = tuple(getattr(snapshot, "transitions"))
        self._sequence += 1
        payload = {
            "schema_version": 1,
            "mission_id": mission_id,
            "mission_status": getattr(mission.status, "value", str(mission.status)),
            "transition_count": len(transitions),
            "latest_transition_id": (
                getattr(transitions[-1], "transition_id", None) if transitions else None
            ),
            "elapsed_seconds": elapsed,
            "status": (
                "passed" if getattr(mission.status, "value", "") == "completed" else "in_progress"
            ),
            "checkpoint": f"mission:{mission_id}:transition:{len(transitions)}",
            "next_action": f"continue existing mission {mission_id} without resubmission",
        }
        path = self._root / f"{self._sequence:06d}-mission-window.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _write_showcase_summary(
    *,
    run_root: Path,
    run_id: str,
    result: ShowcaseRunResult,
    projection_url: str,
) -> Path:
    manifest_path = run_root / "manifest.json"
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    summary_path = run_root / "showcase-result.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "mission_id": result.dialogue.mission_id,
                "mission_status": result.evidence.mission_report.status,
                "manifest_sha256": manifest_sha256,
                "manifest_path": "manifest.json",
                "final_narration": result.evidence.final_narration,
                "projection_url": projection_url,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary_path


def _require_r8_start(ledger_path: Path) -> AcceptanceLedger:
    ledger = AcceptanceLedgerStore(ledger_path).load()
    ledger.require_gate_start("R8")
    return ledger


def _record_r8_result(
    *,
    ledger_path: Path,
    run_root: Path,
    run_id: str,
    result: ShowcaseRunResult,
) -> None:
    store = AcceptanceLedgerStore(ledger_path)
    ledger = store.load()
    failed_stage = next(
        (stage for stage in result.evidence.stages if stage.lifecycle in {"failed", "blocked"}),
        None,
    )
    completed = result.evidence.mission_report.status == "completed" and failed_stage is None
    stage_id = "final-summary" if completed or failed_stage is None else failed_stage.stage_id
    stage_failure = None if failed_stage is None else failed_stage.failure
    failure_code = (
        None
        if completed
        else (stage_failure.code if stage_failure is not None else "MISSION_NOT_COMPLETED")
    )
    failure_layer = (
        None
        if completed
        else (stage_failure.layer if stage_failure is not None else "verification")
    )
    stages = tuple(result.evidence.stages)
    started_at_ms = min(
        (stage.started_at_ms for stage in stages if stage.started_at_ms is not None),
        default=time.time_ns() // 1_000_000,
    )
    finished_at_ms = max(
        (stage.finished_at_ms for stage in stages if stage.finished_at_ms is not None),
        default=started_at_ms,
    )
    evidence_refs = (
        f"file:{(run_root / 'manifest.json').resolve().as_posix()}",
        f"file:{(run_root / 'showcase-result.json').resolve().as_posix()}",
    )
    ledger = ledger.record_real_attempt(
        RealAttempt(
            attempt_id=f"r8:{run_id}",
            run_id=run_id,
            stage_id=stage_id,
            outcome="passed" if completed else "failed",
            failure_code=failure_code,
            failure_layer=failure_layer,
            occurred_at_ms=finished_at_ms,
            evidence_refs=evidence_refs,
        )
    )
    gate_status = (
        "passed"
        if completed
        else "blocked"
        if failed_stage is not None and failed_stage.lifecycle == "blocked"
        else "failed"
    )
    ledger = ledger.record_gate(
        gate="R8",
        status=gate_status,
        attempt_id=f"gate-r8:{run_id}",
        started_at_ms=started_at_ms,
        finished_at_ms=finished_at_ms,
        evidence_refs=evidence_refs,
        failure_code=failure_code,
    )
    store.save(ledger)


async def run(
    *,
    repository_dir: Path,
    output_root: Path,
    scratch_root: Path,
    run_id: str,
    completion_timeout_seconds: float,
    ledger_path: Path,
    bounded_feedback: bool = False,
) -> Path:
    _require_r8_start(ledger_path)
    scenario = default_showcase_scenario()
    runtime_root = (scratch_root / "runtime" / run_id).resolve()
    capture_root = (scratch_root / "capture" / run_id).resolve()
    external_runtime = resolve_external_runtime_dir(repository_dir)
    server = MinecraftReviewServerLease(
        repository_dir=repository_dir,
        world_dir=runtime_root / "_world",
        world_seed=scenario.world_seed,
    )
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(runtime_root / "stores" / "mission.sqlite3"),
        skill_path=str(runtime_root / "stores" / "skill.sqlite3"),
        max_tool_wait_seconds=60,
        bot=MinecraftBotConfig(
            host="127.0.0.1",
            port=25566,
            username=scenario.bot_username,
            version="1.21",
        ),
        client_viewer=MinecraftClientViewerConfig(
            enabled=True,
            username=scenario.viewer_username,
            auto_spectate=True,
            poll_interval=2,
            spectate_timeout=8,
        ),
        runtime=MinecraftRuntimeConfig(
            runtime_path=str(external_runtime),
            entrypoint="src/index.js",
            package_manager="npm",
            use_embedded_fallback=False,
        ),
    )
    bridge = MinecraftBridge(config)
    capture = DesktopShowcaseCapture(working_root=capture_root)
    environment = ReviewScenarioEnvironment(
        runtime_root=runtime_root,
        server=server,
        bridge=bridge,
    )
    preparer = ScenarioPreparer(
        executor=ReviewRconSetupExecutor(server),
        environment=environment,
        now_ms=lambda: time.time_ns() // 1_000_000,
    )
    projection_server = await ShowcaseProjectionServer.start(
        frontend_dist=repository_dir / "frontend" / "dist"
    )
    projection_url = projection_server.walkthrough_url(run_id)
    print(f"[SHOWCASE_PROJECTION_URL] {projection_url}", flush=True)
    llm = None
    submitter = None
    backend = None
    try:
        llm = configured_showcase_llm_from_environment()
        submitter = await create_ordinary_showcase_submitter(llm=llm)
        narrator = ConfiguredModelEvidenceNarrator(llm)
        backend = LiveShowcaseBackend(
            bridge=bridge,
            submitter=submitter,
            narrator=narrator,
            capture_probe_path=capture.capture_probe_path,
            completion_timeout_seconds=completion_timeout_seconds,
            event_emit=projection_server.relay.emit,
            mission_feedback=(
                _MissionFeedbackWriter(output_root / run_id / "feedback")
                if bounded_feedback
                else None
            ),
        )
        runner = ShowcaseRunner(
            scenario_preparer=preparer,
            backend=backend,
            capture=capture,
            output_root=output_root,
            projection_publisher=ProjectionEventPublisher(emit=projection_server.relay.emit),
        )
        result = await runner.run(run_id=run_id, user_text=SHOWCASE_USER_TEXT)
        run_root = output_root.resolve() / run_id
        summary_path = _write_showcase_summary(
            run_root=run_root,
            run_id=run_id,
            result=result,
            projection_url=projection_url,
        )
        _record_r8_result(
            ledger_path=ledger_path,
            run_root=run_root,
            run_id=run_id,
            result=result,
        )
        return summary_path
    finally:
        try:
            if backend is not None:
                await backend.close()
            else:
                if submitter is not None:
                    await submitter.close()
                if llm is not None:
                    await llm.close()
        finally:
            try:
                await server.stop()
            finally:
                await projection_server.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-dir", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/showcase-runs"),
    )
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/showcase-scratch"),
    )
    parser.add_argument(
        "--run-id",
        default=f"adaptive-showcase-{time.time_ns() // 1_000_000}",
    )
    parser.add_argument("--completion-timeout-seconds", type=float, default=1_200)
    parser.add_argument("--bounded-feedback", action="store_true")
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/acceptance-ledger.json"),
    )
    args = parser.parse_args()
    output = asyncio.run(
        run(
            repository_dir=args.repository_dir.resolve(),
            output_root=args.output_root,
            scratch_root=args.scratch_root,
            run_id=args.run_id,
            completion_timeout_seconds=args.completion_timeout_seconds,
            ledger_path=args.ledger_path.resolve(),
            bounded_feedback=args.bounded_feedback,
        )
    )
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
