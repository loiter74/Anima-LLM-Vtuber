from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import Field, model_validator

from .leases import LeaseManager, ResourceInspector
from .models import (
    ActionResult,
    CleanupStrategy,
    ExecutionPlanManifest,
    FeedbackBudget,
    FeedbackStatus,
    FrozenModel,
    LeaseDecision,
    PlanStepSpec,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceObservation,
    ResourceOwnership,
)


class LifecycleStepKind(StrEnum):
    COMMAND = "command"
    BUILD = "build"
    HTTP_CHECK = "http-check"
    LOG_CHECK = "log-check"


class LifecycleStepContract(FrozenModel):
    id: str
    kind: LifecycleStepKind
    depends_on: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    target: str | None = None
    budget: FeedbackBudget = FeedbackBudget()

    @model_validator(mode="after")
    def validate_payload(self) -> LifecycleStepContract:
        command_kinds = {
            LifecycleStepKind.COMMAND,
            LifecycleStepKind.BUILD,
            LifecycleStepKind.LOG_CHECK,
        }
        if self.kind in command_kinds and not self.command:
            raise ValueError(f"{self.kind.value} lifecycle step requires a command")
        if self.kind is LifecycleStepKind.HTTP_CHECK and not self.target:
            raise ValueError("HTTP lifecycle step requires a target URL")
        return self


class FrozenLifecyclePlan(FrozenModel):
    operation: str
    plan: ExecutionPlanManifest
    steps: tuple[LifecycleStepContract, ...]

    @model_validator(mode="after")
    def validate_plan_alignment(self) -> FrozenLifecyclePlan:
        if tuple(step.id for step in self.steps) != tuple(step.id for step in self.plan.steps):
            raise ValueError("lifecycle contracts must align with the frozen execution plan")
        return self


class BuildProcessLaunch(FrozenModel):
    identity: ResourceIdentity
    log_path: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_process(self) -> BuildProcessLaunch:
        if self.identity.kind is not ResourceKind.PROCESS:
            raise ValueError("BuildKit launch requires an exact process identity")
        return self


class BuildProcessDriver(ResourceInspector, Protocol):
    def launch(self, command: tuple[str, ...], *, log_path: str) -> BuildProcessLaunch: ...


def _process_creation_token(pid: int) -> str | None:
    if sys.platform == "win32":
        command = (
            "$p = Get-CimInstance Win32_Process -Filter 'ProcessId = "
            f"{pid}' -ErrorAction SilentlyContinue; "
            "if ($null -ne $p) { $p.CreationDate.ToUniversalTime().ToString('o') }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() or None
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        fields = stat_path.read_text(encoding="utf-8").split()
    except OSError:
        return None
    return fields[21] if len(fields) > 21 else None


class LeasedSubprocessBuildDriver:
    def __init__(
        self,
        *,
        workspace_root: Path,
        artifacts_root: Path,
        receipt_path: Path,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._artifacts_root = artifacts_root.resolve()
        self._receipt_path = receipt_path.resolve()
        self._receipt_path.relative_to(self._artifacts_root)

    def launch(self, command: tuple[str, ...], *, log_path: str) -> BuildProcessLaunch:
        destination = (self._artifacts_root / log_path).resolve()
        destination.relative_to(self._artifacts_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._receipt_path.parent.mkdir(parents=True, exist_ok=True)
        self._receipt_path.unlink(missing_ok=True)
        helper = (
            sys.executable,
            "-m",
            "tooling.execution_feedback.process_runner",
            "--receipt",
            str(self._receipt_path),
            "--",
            *command,
        )
        environment = dict(os.environ)
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(self._workspace_root), existing) if item
        )
        creationflags = 0
        start_new_session = False
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            start_new_session = True
        with destination.open("a", encoding="utf-8", newline="\n") as log:
            process = subprocess.Popen(
                helper,
                cwd=self._workspace_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        creation_token = _process_creation_token(process.pid)
        if creation_token is None:
            process.terminate()
            raise RuntimeError("could not capture the BuildKit helper creation token")
        return BuildProcessLaunch(
            identity=ResourceIdentity(
                kind=ResourceKind.PROCESS,
                resource_id=str(process.pid),
                creation_token=creation_token,
            ),
            log_path=destination.relative_to(self._artifacts_root).as_posix(),
        )

    def inspect(self, identity: ResourceIdentity) -> ResourceObservation:
        if identity.kind is not ResourceKind.PROCESS or not identity.resource_id.isdecimal():
            raise ValueError("BuildKit lease identity must contain a numeric process ID")
        creation_token = _process_creation_token(int(identity.resource_id))
        if creation_token is not None:
            return ResourceObservation(
                identity=ResourceIdentity(
                    kind=ResourceKind.PROCESS,
                    resource_id=identity.resource_id,
                    creation_token=creation_token,
                ),
                running=True,
            )
        exit_code: int | None = None
        try:
            payload = json.loads(self._receipt_path.read_text(encoding="utf-8"))
            candidate = payload.get("exit_code") if isinstance(payload, dict) else None
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                exit_code = candidate
        except (OSError, ValueError, TypeError):
            pass
        return ResourceObservation(identity=identity, running=False, exit_code=exit_code)


class LifecycleDriverObservation(FrozenModel):
    succeeded: bool
    summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    exit_code: int | None = None


class LifecycleDriver(Protocol):
    def run_command(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> LifecycleDriverObservation: ...

    def check_http(
        self,
        target: str,
        *,
        timeout_seconds: float,
    ) -> LifecycleDriverObservation: ...

    def check_logs(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> LifecycleDriverObservation: ...


class LifecycleStepExecutor:
    def __init__(
        self,
        *,
        driver: LifecycleDriver,
        build_controller: BuildStepController | None = None,
    ) -> None:
        self._driver = driver
        self._build_controller = build_controller

    def run(self, step: LifecycleStepContract, *, now: datetime) -> ActionResult:
        if step.kind is LifecycleStepKind.BUILD:
            if self._build_controller is None:
                raise RuntimeError("build lifecycle step requires a BuildStepController")
            return self._build_controller.run(now=now)
        if step.kind is LifecycleStepKind.HTTP_CHECK:
            assert step.target is not None
            observation = self._driver.check_http(
                step.target,
                timeout_seconds=step.budget.action_seconds,
            )
        elif step.kind is LifecycleStepKind.LOG_CHECK:
            observation = self._driver.check_logs(
                step.command,
                timeout_seconds=step.budget.action_seconds,
            )
        else:
            observation = self._driver.run_command(
                step.command,
                timeout_seconds=step.budget.action_seconds,
            )
        return self._observation_result(step, observation)

    @staticmethod
    def _observation_result(
        step: LifecycleStepContract,
        observation: LifecycleDriverObservation,
    ) -> ActionResult:
        if observation.succeeded:
            return ActionResult(
                status=FeedbackStatus.PASSED,
                progress_summary=observation.summary,
                evidence_refs=observation.evidence_refs,
                next_action=f"advance after {step.id}",
            )
        failure_material = (
            f"{step.id}:{step.kind.value}:{observation.exit_code}:{observation.summary}"
        ).encode()
        return ActionResult(
            status=FeedbackStatus.FAILED,
            progress_summary=observation.summary,
            evidence_refs=observation.evidence_refs,
            failure_fingerprint=hashlib.sha256(failure_material).hexdigest(),
            next_action=f"inspect {step.id} evidence before retry",
        )


class BuildStepController:
    def __init__(
        self,
        *,
        lease_manager: LeaseManager,
        driver: BuildProcessDriver,
        run_id: str,
        owner: str,
        lease_id: str,
        command: tuple[str, ...],
        command_digest: str,
        log_path: str,
    ) -> None:
        self._leases = lease_manager
        self._driver = driver
        self._run_id = run_id
        self._owner = owner
        self._lease_id = lease_id
        self._command = command
        self._command_digest = command_digest
        self._log_path = log_path

    def run(self, *, now: datetime) -> ActionResult:
        try:
            lease = self._leases.read(self._run_id, self._lease_id)
        except FileNotFoundError:
            launch = self._driver.launch(self._command, log_path=self._log_path)
            lease = self._leases.register(
                ResourceLease(
                    lease_id=self._lease_id,
                    run_id=self._run_id,
                    owner=self._owner,
                    identity=launch.identity,
                    command_digest=self._command_digest,
                    log_path=launch.log_path,
                    created_at=now,
                    heartbeat_at=now,
                    ttl_seconds=300,
                    cleanup_strategy=CleanupStrategy.TERMINATE_PROCESS_GROUP,
                    ownership=ResourceOwnership.OWNED,
                )
            )
            return self._in_progress(lease, "BuildKit process started with an exact lease")

        inspection = self._leases.inspect(
            self._lease_id,
            inspector=self._driver,
            now=now,
        )
        if inspection.decision is LeaseDecision.MATCHING:
            lease = self._leases.heartbeat(self._lease_id, owner=self._owner, now=now)
            return self._in_progress(lease, "BuildKit process is still running")
        if inspection.decision is LeaseDecision.COMPLETED:
            if inspection.observation.exit_code == 0:
                return ActionResult(
                    status=FeedbackStatus.PASSED,
                    progress_summary="BuildKit process completed successfully",
                    evidence_refs=(lease.log_path,),
                    next_action="start Animetta container",
                )
            return ActionResult(
                status=FeedbackStatus.FAILED,
                progress_summary=(
                    f"BuildKit process exited with {inspection.observation.exit_code}"
                ),
                evidence_refs=(lease.log_path,),
                failure_fingerprint=hashlib.sha256(
                    f"buildkit-exit:{inspection.observation.exit_code}:{lease.command_digest}".encode()
                ).hexdigest(),
                next_action="inspect BuildKit log before retry",
            )
        return ActionResult(
            status=FeedbackStatus.BLOCKED,
            progress_summary=inspection.reason,
            evidence_refs=(lease.log_path,),
            failure_fingerprint=hashlib.sha256(
                f"buildkit-lease:{inspection.decision.value}:{lease.command_digest}".encode()
            ).hexdigest(),
            next_action="inspect the exact BuildKit process lease",
        )

    @staticmethod
    def _in_progress(lease: ResourceLease, summary: str) -> ActionResult:
        return ActionResult(
            status=FeedbackStatus.IN_PROGRESS,
            progress_summary=summary,
            evidence_refs=(lease.log_path,),
            lease=lease.to_ref(),
            next_action="continue monitoring the leased BuildKit process",
        )


def _contracts(operation: str) -> tuple[LifecycleStepContract, ...]:
    definitions: tuple[
        tuple[str, LifecycleStepKind, tuple[str, ...], str | None],
        ...,
    ]
    if operation == "anima-up":
        definitions = (
            ("host-tts-start", LifecycleStepKind.COMMAND, ("host-tts-start",), None),
            (
                "host-tts-preflight",
                LifecycleStepKind.COMMAND,
                ("host-tts-preflight",),
                None,
            ),
            (
                "animetta-build",
                LifecycleStepKind.BUILD,
                ("docker", "compose", "build", "animetta"),
                None,
            ),
            (
                "animetta-start",
                LifecycleStepKind.COMMAND,
                ("docker", "compose", "up", "-d", "--no-build", "animetta"),
                None,
            ),
            ("animetta-health", LifecycleStepKind.HTTP_CHECK, (), "http://localhost/health"),
            ("frontend-readiness", LifecycleStepKind.HTTP_CHECK, (), "http://localhost"),
            (
                "default-log-check",
                LifecycleStepKind.LOG_CHECK,
                ("docker", "compose", "logs", "animetta"),
                None,
            ),
        )
    elif operation == "anima-down":
        definitions = (
            (
                "animetta-cleanup",
                LifecycleStepKind.COMMAND,
                ("docker", "compose", "down", "--remove-orphans"),
                None,
            ),
        )
    elif operation == "host-tts-up":
        definitions = (
            ("host-tts-start", LifecycleStepKind.COMMAND, ("host-tts-start",), None),
            (
                "host-tts-preflight",
                LifecycleStepKind.COMMAND,
                ("host-tts-preflight",),
                None,
            ),
        )
    elif operation == "host-tts-status":
        definitions = (("host-tts-status", LifecycleStepKind.COMMAND, ("host-tts-status",), None),)
    elif operation == "host-tts-stop":
        definitions = (("host-tts-stop", LifecycleStepKind.COMMAND, ("host-tts-stop",), None),)
    else:
        raise ValueError(f"operation does not have a bounded lifecycle plan: {operation}")

    steps: list[LifecycleStepContract] = []
    for index, (step_id, kind, command, target) in enumerate(definitions):
        steps.append(
            LifecycleStepContract(
                id=step_id,
                kind=kind,
                depends_on=() if index == 0 else (definitions[index - 1][0],),
                command=command,
                target=target,
            )
        )
    return tuple(steps)


def freeze_lifecycle_plan(
    operation: str,
    *,
    input_fingerprint: str,
    run_id: str | None = None,
) -> FrozenLifecyclePlan:
    steps = _contracts(operation)
    plan = ExecutionPlanManifest(
        run_id=run_id or f"{operation}-plan",
        input_fingerprint=input_fingerprint,
        steps=tuple(
            PlanStepSpec(
                id=step.id,
                action_kind=f"lifecycle-{step.kind.value}",
                depends_on=step.depends_on,
                budget=step.budget,
            )
            for step in steps
        ),
    )
    return FrozenLifecyclePlan(operation=operation, plan=plan, steps=steps)
