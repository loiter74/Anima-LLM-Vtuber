from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from .leases import LeaseManager, ResourceInspector, ResourceTerminator
from .lifecycle import _process_creation_token
from .models import (
    CleanupStrategy,
    ContinuationRequest,
    FeedbackStatus,
    FeedbackWindowResult,
    LeaseDecision,
    ResourceIdentity,
    ResourceKind,
    ResourceObservation,
)
from .store import IterationPlanStore


def render_feedback_result(result: FeedbackWindowResult) -> str:
    lines = [
        f"{result.step_id} window {result.window_sequence}: {result.status.value} ({result.elapsed_seconds:.1f}s)",
        f"  progress: {result.progress_summary}",
    ]
    if result.evidence_refs:
        lines.append(f"  evidence: {', '.join(result.evidence_refs)}")
    if result.lease is not None:
        lines.extend(
            (
                f"  lease: {result.lease.lease_id}",
                (
                    "  safe cancel: py -3.13 -m tooling.execution_feedback cancel "
                    f"--lease-id {result.lease.lease_id}"
                ),
            )
        )
    lines.append(f"  next: {result.next_action}")
    return "\n".join(lines)


class SystemExactResourceController(ResourceInspector, ResourceTerminator):
    def inspect(self, identity: ResourceIdentity) -> ResourceObservation:
        if identity.kind is ResourceKind.PROCESS:
            if not identity.resource_id.isdecimal():
                raise ValueError("process lease resource ID must be a numeric PID")
            creation_token = _process_creation_token(int(identity.resource_id))
            if creation_token is None:
                return ResourceObservation(identity=identity, running=False)
            return ResourceObservation(
                identity=ResourceIdentity(
                    kind=ResourceKind.PROCESS,
                    resource_id=identity.resource_id,
                    creation_token=creation_token,
                    project=identity.project,
                ),
                running=True,
            )
        result = subprocess.run(
            ["docker", "inspect", identity.resource_id],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ResourceObservation(identity=identity, running=False)
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise RuntimeError("Docker returned an invalid exact-container inspection")
        item = payload[0]
        state = item.get("State")
        if not isinstance(state, dict):
            raise RuntimeError("Docker inspection omitted container State")
        observed = ResourceIdentity(
            kind=ResourceKind.CONTAINER,
            resource_id=str(item.get("Id", "")),
            creation_token=str(state.get("StartedAt", "")),
            project=identity.project,
        )
        return ResourceObservation(identity=observed, running=state.get("Running") is True)

    def terminate(self, identity: ResourceIdentity, strategy: CleanupStrategy) -> bool:
        if identity.kind is ResourceKind.PROCESS:
            pid = int(identity.resource_id)
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )
                return result.returncode == 0
            try:
                kill_process_group = getattr(os, "killpg")
                kill_process_group(pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            return True
        if strategy is not CleanupStrategy.STOP_CONTAINER:
            return False
        result = subprocess.run(
            ["docker", "stop", identity.resource_id],
            capture_output=True,
            check=False,
            timeout=30,
        )
        return result.returncode == 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and recover bounded execution plans.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("artifacts/iteration-plans"),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--run-id", required=True)
    continue_step = commands.add_parser("continue")
    continue_step.add_argument("--run-id", required=True)
    continue_step.add_argument("--step-id", required=True)
    cancel = commands.add_parser("cancel")
    cancel.add_argument("--lease-id", required=True)
    reflection = commands.add_parser("reflection")
    reflection.add_argument("--fingerprint", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    inspector: ResourceInspector | None = None,
    terminator: ResourceTerminator | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    store = IterationPlanStore(args.root)
    current_time = now or (lambda: datetime.now(UTC))
    if args.command == "inspect":
        plan = store.read_plan(args.run_id)
        for step in plan.steps:
            recovery = store.recover_latest_result(plan.run_id, step.id)
            if recovery.result is None:
                print(f"{step.id}: pending")
            else:
                print(render_feedback_result(recovery.result))
        reflections = tuple(
            state.reflection
            for state in store.list_failure_states()
            if state.reflection is not None
            and any(record.run_id == plan.run_id for record in state.occurrences)
        )
        for reflection in reflections:
            print(json.dumps(reflection.model_dump(mode="json"), sort_keys=True))
        return 0
    if args.command == "continue":
        plan = store.read_plan(args.run_id)
        if args.step_id not in {step.id for step in plan.steps}:
            print(f"unknown step: {args.step_id}")
            return 1
        recovery = store.recover_latest_result(args.run_id, args.step_id)
        if recovery.result is None or recovery.result.status is FeedbackStatus.PASSED:
            print("step is not a resumable nonterminal step")
            return 1
        request = ContinuationRequest(
            request_id=f"request-{uuid.uuid4().hex}",
            run_id=args.run_id,
            step_id=args.step_id,
            requested_at=current_time(),
        )
        path = store.write_continuation_request(request)
        print(path.resolve().as_posix())
        return 0
    if args.command == "cancel":
        system = SystemExactResourceController()
        outcome = LeaseManager(store).cancel(
            args.lease_id,
            inspector=inspector or system,
            terminator=terminator or system,
            now=current_time(),
        )
        print(json.dumps(outcome.model_dump(mode="json"), sort_keys=True))
        return 0 if outcome.decision is LeaseDecision.CANCELLED else 1
    state = store.read_failure_state(args.fingerprint)
    if state is None or state.reflection is None:
        print("no open reflection for fingerprint")
        return 1
    print(json.dumps(state.reflection.model_dump(mode="json"), sort_keys=True))
    return 0
