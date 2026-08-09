"""Run one lowest-layer real Minecraft gate without invoking the full R8 scene."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
from animetta.tools.minecraft.core.config import MinecraftConfig, MinecraftMcpConfig
from animetta.tools.minecraft.core.tools import (
    bind_minecraft_caller_scope,
    cleanup_bridge,
    configure_voyager_control_plane,
    mc_operate_bot,
)
from animetta.tools.minecraft.mission.adaptive import ExplorationFrontier
from animetta.tools.minecraft.mission.models import MissionSpec
from animetta.tools.minecraft.mission.repository import MissionStatus
from animetta.tools.minecraft.showcase.live import (
    ReviewRconSetupExecutor,
    ReviewScenarioEnvironment,
)
from animetta.tools.minecraft.showcase.micro_gates import (
    build_acquisition_mission,
    build_combat_mission,
    build_construction_mission,
    stage_receipts_passed,
)
from animetta.tools.minecraft.showcase.promotion import AcceptanceLedgerStore, RealAttempt
from animetta.tools.minecraft.showcase.scenario import (
    ScenarioPreparer,
    default_showcase_scenario,
)
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint

_TERMINAL = {
    MissionStatus.COMPLETED,
    MissionStatus.FAILED,
    MissionStatus.CANCELLED,
    MissionStatus.BLOCKED_UNKNOWN,
}


class _FeedbackJournal:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._sequence = 0

    async def publish(
        self,
        step_id: str,
        status: str,
        summary: str,
        evidence_refs: tuple[str, ...],
        checkpoint: str | None,
    ) -> None:
        self._sequence += 1
        payload = {
            "schema_version": 1,
            "step_id": step_id,
            "window_sequence": self._sequence,
            "status": status,
            "progress_summary": summary,
            "evidence_refs": evidence_refs,
            "checkpoint": checkpoint,
            "next_action": (
                f"continue {step_id} from checkpoint"
                if status == "in_progress"
                else f"advance after {step_id}"
            ),
        }
        path = self._root / f"{self._sequence:06d}-{step_id}.json"
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


def _record_r7_result(
    *,
    ledger_path: Path,
    artifact_path: Path,
    run_id: str,
    started_at_ms: int,
    finished_at_ms: int,
) -> None:
    store = AcceptanceLedgerStore(ledger_path)
    ledger = store.load()
    evidence_refs = (f"file:{artifact_path.resolve().as_posix()}",)
    ledger = ledger.record_real_attempt(
        RealAttempt(
            attempt_id=f"r7:{run_id}",
            run_id=run_id,
            stage_id="ledger-settlement",
            outcome="passed",
            occurred_at_ms=finished_at_ms,
            evidence_refs=evidence_refs,
        )
    )
    ledger = ledger.record_gate(
        gate="R7",
        status="passed",
        attempt_id=f"gate-r7:{run_id}",
        started_at_ms=started_at_ms,
        finished_at_ms=finished_at_ms,
        evidence_refs=evidence_refs,
    )
    store.save(ledger)


def _dump(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[attr-defined]
    return value


class _ViewerTracker:
    def __init__(self) -> None:
        self.following = asyncio.Event()
        self.latest: dict[str, Any] = {}

    def receive(self, event_type: str, payload: object) -> None:
        if event_type != "client_viewer_status" or not isinstance(payload, dict):
            return
        self.latest = dict(payload)
        if (
            payload.get("binding_state", payload.get("state")) == "following"
            and payload.get("confirmed") is True
        ):
            self.following.set()
        else:
            self.following.clear()

    async def wait(self, timeout_seconds: float) -> dict[str, Any]:
        async with asyncio.timeout(timeout_seconds):
            await self.following.wait()
        return dict(self.latest)


async def _execute_mission(
    *,
    control_plane: Any,
    mission: MissionSpec,
    caller_scope: str,
    timeout_seconds: float,
    step_id: str,
    feedback: Callable[
        [str, str, str, tuple[str, ...], str | None],
        Awaitable[None],
    ]
    | None = None,
) -> dict[str, Any]:
    with bind_minecraft_caller_scope(caller_scope):
        raw_handle = await mc_operate_bot.ainvoke(
            {
                "operation": "execute",
                "execute": {
                    "contract_version": "2",
                    "kind": "mission",
                    "request_id": f"request-{mission.mission_id}",
                    "mission": mission.model_dump(mode="python"),
                },
            }
        )
    handle = json.loads(raw_handle)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    feedback_at = asyncio.get_running_loop().time()
    last_transition_count = -1
    snapshot = await control_plane.mission_repository.snapshot(mission.mission_id)
    while snapshot.mission.status not in _TERMINAL:
        transition_count = len(snapshot.transitions)
        now = asyncio.get_running_loop().time()
        if feedback is not None and (
            transition_count != last_transition_count or now - feedback_at >= 60
        ):
            await feedback(
                step_id,
                "in_progress",
                f"mission {mission.mission_id} has {transition_count} committed transitions",
                (f"mission:{mission.mission_id}:transitions:{transition_count}",),
                f"mission:{mission.mission_id}:transition:{transition_count}",
            )
            feedback_at = now
            last_transition_count = transition_count
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"MICRO_GATE_TIMEOUT:{mission.mission_id}")
        await asyncio.sleep(0.5)
        snapshot = await control_plane.mission_repository.snapshot(mission.mission_id)

    command_ids = tuple(
        dict.fromkeys(
            str(transition.details["command_id"])
            for transition in snapshot.transitions
            if isinstance(transition.details.get("command_id"), str)
        )
    )
    command_records: list[Any] = []
    step_records: list[Any] = []
    for command_id in command_ids:
        command = await control_plane.repository.get_command(command_id)
        if command is not None:
            command_records.append(command)
        step_records.extend(await control_plane.repository.list_steps(command_id))
    commands = tuple(command_records)
    steps = tuple(step_records)
    receipts = tuple(step.receipt for step in steps if step.receipt is not None)
    advancements: dict[str, object] = {}
    for command_id in command_ids:
        for event in await control_plane.evidence_collector.current_advancement_events(command_id):
            advancements[event.content_hash] = event.model_dump(mode="json")
    result = {
        "mission": mission.model_dump(mode="json"),
        "handle": handle,
        "status": snapshot.mission.status.value,
        "objective_states": tuple(objective.status.value for objective in snapshot.objectives),
        "commands": tuple(_dump(command) for command in commands),
        "receipts": tuple(receipts),
        "advancements": tuple(advancements[key] for key in sorted(advancements)),
        "passed": (
            snapshot.mission.status is MissionStatus.COMPLETED
            and all(objective.status.value == "completed" for objective in snapshot.objectives)
        ),
    }
    if feedback is not None:
        await feedback(
            step_id,
            "passed" if result["passed"] else "failed",
            f"mission {mission.mission_id} reached {snapshot.mission.status.value}",
            (f"mission:{mission.mission_id}:transitions:{len(snapshot.transitions)}",),
            f"mission:{mission.mission_id}:transition:{len(snapshot.transitions)}",
        )
    return result


async def _skill_evidence(control_plane: Any) -> dict[str, Any]:
    manifest = await control_plane.adapter.get_manifest()
    environment = stable_environment_fingerprint(manifest.profile)
    revisions, trusts = await control_plane.skill_store.load_live_catalog(
        environment_fingerprint=environment
    )
    records: list[dict[str, Any]] = []
    for revision_hash, revision in revisions.items():
        matching = tuple(trust for trust in trusts if trust.revision_hash == revision_hash)
        validations = await control_plane.skill_store.load_independent_validation_evidence(
            revision_hash=revision_hash,
            environment_fingerprint=environment,
        )
        records.append(
            {
                "revision": revision.model_dump(mode="json"),
                "trust": tuple(trust.model_dump(mode="json") for trust in matching),
                "independent_validations": tuple(
                    validation.model_dump(mode="json") for validation in validations
                ),
            }
        )
    return {
        "environment_fingerprint": environment,
        "records": tuple(records),
    }


def _selected_strategy(command: object) -> str | None:
    if not isinstance(command, dict):
        return None
    terminal = command.get("terminal_result")
    if not isinstance(terminal, dict):
        return None
    output = terminal.get("output")
    if not isinstance(output, dict):
        return None
    selected = output.get("selected_strategy")
    return selected if isinstance(selected, str) else None


async def run(
    *,
    repository_dir: Path,
    output_root: Path,
    scratch_root: Path,
    ledger_path: Path,
    run_id: str,
    timeout_seconds: float,
    viewer_timeout_seconds: float,
) -> Path:
    ledger = AcceptanceLedgerStore(ledger_path).load()
    ledger.require_gate_start("R7")
    scenario = default_showcase_scenario()
    runtime_root = (scratch_root / run_id / "runtime").resolve()
    run_root = (output_root / run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    artifact_path = run_root / "micro-gate.json"
    feedback_journal = _FeedbackJournal(run_root / "feedback")
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(runtime_root / "stores" / "mission.sqlite3"),
        skill_path=str(runtime_root / "stores" / "skill.sqlite3"),
        max_tool_wait_seconds=60,
        mcp=MinecraftMcpConfig(default_profile="managed-review"),
    )
    bridge = MinecraftMcpBridge(config)
    viewer = _ViewerTracker()
    bridge.set_viewer_callback(viewer.receive)
    environment = ReviewScenarioEnvironment(
        runtime_root=runtime_root,
        bridge=bridge,
    )
    preparer = ScenarioPreparer(
        executor=ReviewRconSetupExecutor(bridge),
        environment=environment,
        now_ms=lambda: time.time_ns() // 1_000_000,
    )
    artifact: dict[str, Any] = {
        "schema_version": "1",
        "run_id": run_id,
        "scenario_hash": scenario.canonical_hash,
        "started_at_ms": time.time_ns() // 1_000_000,
        "stages": [],
        "passed": False,
    }

    def persist() -> None:
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    persist()
    try:
        scenario_receipt = await preparer.prepare(scenario, run_id=run_id)
        artifact["scenario_receipt"] = scenario_receipt.model_dump(mode="json")
        persist()
        artifact["viewer"] = await viewer.wait(min(viewer_timeout_seconds, 240))
        persist()
        await feedback_journal.publish(
            "viewer-readiness",
            "passed",
            "viewer binding was confirmed",
            (f"viewer:{artifact['viewer'].get('username', '')}:following",),
            None,
        )
        control_plane = await configure_voyager_control_plane(
            bridge,
            blueprint_origins={
                "starter-shelter-v1": (
                    scenario.build_origin.x,
                    scenario.build_origin.y,
                    scenario.build_origin.z,
                )
            },
            entity_origins={
                zone.entity_type: (zone.spawn.x, zone.spawn.y, zone.spawn.z)
                for zone in scenario.monster_zones
            },
            adaptive_frontier=ExplorationFrontier(
                x=scenario.hidden_resources[0].position.x,
                y=scenario.hidden_resources[0].position.y,
                z=scenario.hidden_resources[0].position.z,
                target_block=scenario.hidden_resources[0].item_id,
                target_item="minecraft:raw_copper",
            ),
        )
        caller_scope = f"r7:{run_id}"
        combat_missions = tuple(
            build_combat_mission(
                mission_id=f"{run_id}-combat-{entity.rsplit(':', 1)[-1]}",
                entity=entity,
            )
            for entity in ("minecraft:zombie", "minecraft:skeleton", "minecraft:spider")
        )
        construction = build_construction_mission(mission_id=f"{run_id}-construction")
        learning, reuse = build_acquisition_mission(mission_prefix=f"{run_id}-acquisition")
        missions = (*combat_missions, construction, learning, reuse)
        mission_step_ids = (
            "combat-zombie",
            "combat-skeleton",
            "combat-spider",
            "construction",
            "learning",
            "trusted-reuse",
        )
        boundary = preparer.start_mission(scenario_receipt, mission_id=missions[0].mission_id)
        artifact["mission_start_boundary"] = boundary.model_dump(mode="json")
        persist()
        for mission, step_id in zip(missions, mission_step_ids, strict=True):
            stage = await _execute_mission(
                control_plane=control_plane,
                mission=mission,
                caller_scope=caller_scope,
                timeout_seconds=timeout_seconds,
                step_id=step_id,
                feedback=feedback_journal.publish,
            )
            artifact["stages"].append(stage)
            persist()
            if not stage["passed"]:
                raise RuntimeError(f"MICRO_GATE_STAGE_FAILED:{mission.mission_id}")
        skill_evidence = await _skill_evidence(control_plane)
        artifact["skill_evidence"] = skill_evidence
        strategies = tuple(
            _selected_strategy(command)
            for stage in artifact["stages"][-2:]
            for command in stage["commands"]
        )
        validations = tuple(
            validation
            for record in skill_evidence["records"]
            for validation in record["independent_validations"]
        )
        trusted = tuple(
            trust
            for record in skill_evidence["records"]
            for trust in record["trust"]
            if trust["status"] == "trusted"
        )
        independent = any(
            validation["learning"]["resource_instance_ref"]
            != validation["validation"]["resource_instance_ref"]
            for validation in validations
        )
        await feedback_journal.publish(
            "independent-validation",
            "passed" if independent else "failed",
            "independent validation used a distinct resource instance",
            tuple(
                str(validation.get("validation", {}).get("resource_instance_ref", ""))
                for validation in validations
            ),
            None,
        )
        stage_checks = {
            "combat": all(
                stage_receipts_passed(stage, "attack") for stage in artifact["stages"][:3]
            ),
            "construction": stage_receipts_passed(artifact["stages"][3], "place"),
            "skill-learning-validation": (
                stage_receipts_passed(artifact["stages"][4], "collect")
                and bool(trusted)
                and independent
                and "learn" in strategies
            ),
            "skill-reuse": (
                stage_receipts_passed(artifact["stages"][5], "collect") and "live" in strategies
            ),
        }
        artifact["stage_checks"] = stage_checks
        stage_checks_passed = all(stage_checks.values())
        artifact["finished_at_ms"] = time.time_ns() // 1_000_000
        persist()
        await feedback_journal.publish(
            "projection",
            "passed",
            "micro-gate projection artifact is current",
            (f"file:{artifact_path.resolve().as_posix()}",),
            None,
        )
        if not stage_checks_passed:
            raise RuntimeError("MICRO_GATE_EVIDENCE_FAILED")
        _record_r7_result(
            ledger_path=ledger_path,
            artifact_path=artifact_path,
            run_id=run_id,
            started_at_ms=int(artifact["started_at_ms"]),
            finished_at_ms=int(artifact["finished_at_ms"]),
        )
        artifact["passed"] = True
        persist()
        await feedback_journal.publish(
            "ledger-settlement",
            "passed",
            "R7 real attempt and gate result were durably settled",
            (f"file:{ledger_path.resolve().as_posix()}",),
            None,
        )
        return artifact_path
    except Exception as exc:
        artifact["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        artifact["finished_at_ms"] = time.time_ns() // 1_000_000
        persist()
        raise
    finally:
        if bridge.is_running:
            await bridge.shutdown_runtime(request_id=f"micro-gate-shutdown-{run_id}")
        await cleanup_bridge()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-dir", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/micro-gates"),
    )
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/micro-scratch"),
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=Path("artifacts/minecraft-adaptive-mission/acceptance-ledger.json"),
    )
    parser.add_argument(
        "--run-id",
        default=f"r7-micro-{time.time_ns() // 1_000_000}",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--viewer-timeout-seconds", type=float, default=600)
    args = parser.parse_args()
    output = asyncio.run(
        run(
            repository_dir=args.repository_dir.resolve(),
            output_root=args.output_root.resolve(),
            scratch_root=args.scratch_root.resolve(),
            ledger_path=args.ledger_path.resolve(),
            run_id=args.run_id,
            timeout_seconds=args.timeout_seconds,
            viewer_timeout_seconds=args.viewer_timeout_seconds,
        )
    )
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
