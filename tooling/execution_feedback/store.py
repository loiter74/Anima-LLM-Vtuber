from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from .models import (
    ArtifactRecovery,
    ContinuationRequest,
    ExecutionPlanManifest,
    FailureCircuitState,
    FeedbackEvent,
    FeedbackWindowResult,
    PlanStepCheckpoint,
    ResourceLease,
    validate_identifier,
    validate_sha256,
)


class IterationPlanStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write_plan(self, plan: ExecutionPlanManifest) -> Path:
        return self._atomic_write(
            self.root / plan.run_id / "plan.json",
            plan.model_dump(mode="json"),
        )

    def read_plan(self, run_id: str) -> ExecutionPlanManifest:
        validate_identifier(run_id)
        path = self.root / run_id / "plan.json"
        return ExecutionPlanManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def write_continuation_request(self, request: ContinuationRequest) -> Path:
        return self._atomic_write(
            self.root / request.run_id / "continuation-requests" / f"{request.request_id}.json",
            request.model_dump(mode="json"),
        )

    def list_continuation_requests(self, run_id: str) -> tuple[ContinuationRequest, ...]:
        validate_identifier(run_id)
        directory = self.root / run_id / "continuation-requests"
        if not directory.is_dir():
            return ()
        requests = tuple(
            ContinuationRequest.model_validate_json(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.json")
        )
        return tuple(
            sorted(requests, key=lambda request: (request.requested_at, request.request_id))
        )

    def write_checkpoint(self, checkpoint: PlanStepCheckpoint) -> Path:
        return self._atomic_write(
            self._checkpoint_path(checkpoint.run_id, checkpoint.step_id),
            checkpoint.model_dump(mode="json"),
        )

    def read_checkpoint(self, run_id: str, step_id: str) -> PlanStepCheckpoint | None:
        path = self._checkpoint_path(run_id, step_id)
        if not path.is_file():
            return None
        try:
            return PlanStepCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_event(self, event: FeedbackEvent) -> Path:
        directory = self._window_dir(event.run_id, event.step_id, event.window_sequence) / "events"
        event_index = len(tuple(directory.glob("*.json"))) if directory.is_dir() else 0
        path = directory / f"{event_index:06d}-{event.kind.value}.json"
        return self._atomic_write(path, event.model_dump(mode="json"))

    def list_events(
        self,
        *,
        run_id: str,
        step_id: str,
        window_sequence: int,
    ) -> tuple[FeedbackEvent, ...]:
        directory = self._window_dir(run_id, step_id, window_sequence) / "events"
        if not directory.is_dir():
            return ()
        return tuple(
            FeedbackEvent.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        )

    def read_result(
        self,
        run_id: str,
        step_id: str,
        window_sequence: int,
    ) -> FeedbackWindowResult:
        path = self._window_dir(run_id, step_id, window_sequence) / "result.json"
        return FeedbackWindowResult.model_validate_json(path.read_text(encoding="utf-8"))

    def recover_latest_result(self, run_id: str, step_id: str) -> ArtifactRecovery:
        validate_identifier(run_id)
        validate_identifier(step_id)
        windows = self.root / run_id / "steps" / step_id / "windows"
        rejected: list[str] = []
        if not windows.is_dir():
            return ArtifactRecovery()
        for directory in sorted(
            (path for path in windows.iterdir() if path.is_dir()),
            reverse=True,
        ):
            path = directory / "result.json"
            if not path.is_file():
                continue
            try:
                result = FeedbackWindowResult.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                rejected.append(path.resolve().as_posix())
                continue
            return ArtifactRecovery(
                result=result,
                latest_window_sequence=result.window_sequence,
                rejected_artifacts=tuple(rejected),
            )
        return ArtifactRecovery(rejected_artifacts=tuple(rejected))

    def write_lease(self, lease: ResourceLease) -> Path:
        return self._atomic_write(
            self._lease_path(lease.run_id, lease.lease_id),
            lease.model_dump(mode="json"),
        )

    def read_lease(self, run_id: str, lease_id: str) -> ResourceLease:
        path = self._lease_path(run_id, lease_id)
        return ResourceLease.model_validate_json(path.read_text(encoding="utf-8"))

    def find_lease(self, lease_id: str) -> ResourceLease:
        validate_identifier(lease_id)
        paths = tuple(self.root.glob(f"*/leases/{lease_id}.json"))
        if len(paths) != 1:
            raise LookupError(f"expected exactly one lease {lease_id!r}, found {len(paths)}")
        return ResourceLease.model_validate_json(paths[0].read_text(encoding="utf-8"))

    def list_leases(self, run_id: str) -> tuple[ResourceLease, ...]:
        validate_identifier(run_id)
        directory = self.root / run_id / "leases"
        if not directory.is_dir():
            return ()
        return tuple(
            ResourceLease.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        )

    def write_failure_state(self, state: FailureCircuitState) -> Path:
        return self._atomic_write(
            self._failure_state_path(state.fingerprint),
            state.model_dump(mode="json"),
        )

    def read_failure_state(self, fingerprint: str) -> FailureCircuitState | None:
        path = self._failure_state_path(fingerprint)
        if not path.is_file():
            return None
        return FailureCircuitState.model_validate_json(path.read_text(encoding="utf-8"))

    def list_failure_states(self) -> tuple[FailureCircuitState, ...]:
        directory = self.root / "failure-circuits"
        if not directory.is_dir():
            return ()
        return tuple(
            FailureCircuitState.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        )

    def publish_result(
        self,
        result: FeedbackWindowResult,
        *,
        emit: Callable[[dict[str, object]], None] | None = None,
    ) -> Path:
        payload = result.model_dump(mode="json")
        path = self._atomic_write(
            self._window_dir(result.run_id, result.step_id, result.window_sequence) / "result.json",
            payload,
        )
        if emit is not None:
            emit(payload)
        return path

    def _window_dir(self, run_id: str, step_id: str, window_sequence: int) -> Path:
        validate_identifier(run_id)
        validate_identifier(step_id)
        if window_sequence < 1:
            raise ValueError("window_sequence must be at least 1")
        return self.root / run_id / "steps" / step_id / "windows" / f"{window_sequence:06d}"

    def _lease_path(self, run_id: str, lease_id: str) -> Path:
        validate_identifier(run_id)
        validate_identifier(lease_id)
        return self.root / run_id / "leases" / f"{lease_id}.json"

    def _checkpoint_path(self, run_id: str, step_id: str) -> Path:
        validate_identifier(run_id)
        validate_identifier(step_id)
        return self.root / run_id / "steps" / step_id / "checkpoint.json"

    def _failure_state_path(self, fingerprint: str) -> Path:
        validate_sha256(fingerprint, field_name="fingerprint")
        return self.root / "failure-circuits" / f"{fingerprint}.json"

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, object]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path
