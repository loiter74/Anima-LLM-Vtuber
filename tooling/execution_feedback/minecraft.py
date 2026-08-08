from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, field_validator

from .models import (
    ActionResult,
    CheckpointRef,
    ExecutionPlanManifest,
    FeedbackStatus,
    FrozenModel,
    PlanAggregate,
    PlanStepSpec,
    validate_identifier,
)
from .plan import aggregate_plan_status


class ViewerBridge(Protocol):
    async def binding_status(self) -> tuple[bool, str]: ...

    async def capture(self) -> str: ...


class AsyncClock(Protocol):
    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class ViewerReadinessAdapter:
    def __init__(
        self,
        bridge: ViewerBridge,
        *,
        clock: AsyncClock,
        action_seconds: float = 240,
        poll_seconds: float = 30,
    ) -> None:
        if action_seconds <= 0 or action_seconds > 240:
            raise ValueError("viewer action budget must be in (0, 240]")
        if poll_seconds <= 0 or poll_seconds > action_seconds:
            raise ValueError("viewer polling interval must fit the action budget")
        self._bridge = bridge
        self._clock = clock
        self._action_seconds = action_seconds
        self._poll_seconds = poll_seconds

    async def wait_ready(self) -> ActionResult:
        started = self._clock.monotonic()
        latest_binding = "viewer binding not observed"
        while self._clock.monotonic() - started < self._action_seconds:
            bound, latest_binding = await self._bridge.binding_status()
            if bound:
                capture = await self._bridge.capture()
                return ActionResult(
                    status=FeedbackStatus.PASSED,
                    progress_summary="Minecraft viewer is bound and freshly captured",
                    evidence_refs=(latest_binding, capture),
                    next_action="advance to the first Minecraft mission stage",
                )
            remaining = self._action_seconds - (self._clock.monotonic() - started)
            await self._clock.sleep(min(self._poll_seconds, remaining))
        return ActionResult(
            status=FeedbackStatus.TIMED_OUT,
            progress_summary="Minecraft viewer readiness reached its action boundary",
            evidence_refs=(latest_binding,),
            next_action="ask the user to bind the viewer; never control or restart Minecraft",
        )


class MissionWindowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MissionWindowSnapshot(FrozenModel):
    schema_version: Literal[1] = 1
    mission_id: str
    status: MissionWindowStatus
    transition_sequence: int = Field(ge=0)
    objective_reference: str = Field(min_length=1)
    budget_reference: str = Field(min_length=1)
    receipt_reference: str = Field(min_length=1)
    world_state_reference: str = Field(min_length=1)
    advancement_reference: str = Field(min_length=1)
    skill_version_reference: str = Field(min_length=1)
    captured_at: datetime

    @field_validator("mission_id")
    @classmethod
    def validate_mission_id(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value

    @property
    def evidence_references(self) -> tuple[str, ...]:
        return (
            self.objective_reference,
            self.budget_reference,
            self.receipt_reference,
            self.world_state_reference,
            self.advancement_reference,
            self.skill_version_reference,
        )


class MissionSnapshotRepository(Protocol):
    async def snapshot(self, mission_id: str) -> MissionWindowSnapshot: ...


class MissionCheckpointStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write(self, snapshot: MissionWindowSnapshot) -> Path:
        path = self.root / snapshot.mission_id / "mission-window-checkpoint.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(snapshot.model_dump(mode="json"), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def read(self, mission_id: str) -> MissionWindowSnapshot:
        validate_identifier(mission_id)
        path = self.root / mission_id / "mission-window-checkpoint.json"
        return MissionWindowSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


class MissionWindowAdapter:
    def __init__(
        self,
        repository: MissionSnapshotRepository,
        *,
        store: MissionCheckpointStore,
    ) -> None:
        self._repository = repository
        self._store = store

    async def capture(self, mission_id: str) -> ActionResult:
        validate_identifier(mission_id)
        snapshot = await self._repository.snapshot(mission_id)
        path = self._store.write(snapshot)
        checkpoint = CheckpointRef(
            kind="minecraft-mission",
            reference=path.resolve().as_posix(),
        )
        evidence = (*snapshot.evidence_references, path.resolve().as_posix())
        if snapshot.status in {MissionWindowStatus.PENDING, MissionWindowStatus.RUNNING}:
            return ActionResult(
                status=FeedbackStatus.IN_PROGRESS,
                progress_summary=(
                    f"Mission {mission_id} is {snapshot.status.value} at transition "
                    f"{snapshot.transition_sequence}"
                ),
                evidence_refs=evidence,
                checkpoint=checkpoint,
                next_action=f"continue existing mission {mission_id} without resubmission",
            )
        if snapshot.status is MissionWindowStatus.SUCCEEDED:
            return ActionResult(
                status=FeedbackStatus.PASSED,
                progress_summary=f"Mission {mission_id} reached a committed success transition",
                evidence_refs=evidence,
                checkpoint=checkpoint,
                next_action="run independent mission evidence verification",
            )
        return ActionResult(
            status=(
                FeedbackStatus.CANCELLED
                if snapshot.status is MissionWindowStatus.CANCELLED
                else FeedbackStatus.FAILED
            ),
            progress_summary=f"Mission {mission_id} is {snapshot.status.value}",
            evidence_refs=evidence,
            checkpoint=checkpoint,
            next_action=f"inspect mission {mission_id} transitions before retry",
        )


class MinecraftActionRequest(FrozenModel):
    action_id: str
    safety_action: bool = False

    @field_validator("action_id")
    @classmethod
    def validate_action_id(cls, value: str) -> str:
        return validate_identifier(value)


class BoundaryAdmission(FrozenModel):
    allowed: bool
    reason: str = Field(min_length=1)


class FallbackReceipt(FrozenModel):
    receipt_id: str
    action_id: str
    evidence_reference: str = Field(min_length=1)
    safety_only: Literal[True] = True
    can_satisfy_objective: Literal[False] = False

    @field_validator("receipt_id", "action_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)


def boundary_admission(
    request: MinecraftActionRequest,
    *,
    action_boundary_reached: bool,
) -> BoundaryAdmission:
    if not action_boundary_reached:
        return BoundaryAdmission(allowed=True, reason="action budget remains")
    if request.safety_action:
        return BoundaryAdmission(
            allowed=True,
            reason="survival fallback may reach a committed safe boundary",
        )
    return BoundaryAdmission(
        allowed=False,
        reason="new non-safety Minecraft actions stop at the action boundary",
    )


def build_r7_feedback_plan(
    *,
    run_id: str,
    input_fingerprint: str,
) -> ExecutionPlanManifest:
    step_ids = (
        "viewer-readiness",
        "combat-zombie",
        "combat-skeleton",
        "combat-spider",
        "construction",
        "learning",
        "independent-validation",
        "trusted-reuse",
        "projection",
        "ledger-settlement",
    )
    return ExecutionPlanManifest(
        run_id=run_id,
        input_fingerprint=input_fingerprint,
        steps=tuple(
            PlanStepSpec(
                id=step_id,
                action_kind="minecraft-r7-stage",
                depends_on=() if index == 0 else (step_ids[index - 1],),
            )
            for index, step_id in enumerate(step_ids)
        ),
    )


def aggregate_minecraft_stages(
    plan: ExecutionPlanManifest,
    statuses: dict[str, FeedbackStatus],
) -> PlanAggregate:
    return aggregate_plan_status(plan, statuses)
