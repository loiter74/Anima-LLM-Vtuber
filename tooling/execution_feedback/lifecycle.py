from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

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
    validate_identifier,
)


class LifecycleStepKind(StrEnum):
    COMMAND = "command"
    BUILD = "build"
    HTTP_CHECK = "http-check"
    LOG_CHECK = "log-check"
    CAPTURE_QWEN = "capture-qwen"
    VERIFY_QWEN = "verify-qwen"


class ContainerIdentity(FrozenModel):
    container_id: str = Field(min_length=1)
    image_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)

    @property
    def evidence_reference(self) -> str:
        material = f"{self.container_id}:{self.image_id}:{self.started_at}".encode()
        return f"qwen-identity:{hashlib.sha256(material).hexdigest()}"


class LifecycleStepContract(FrozenModel):
    id: str
    kind: LifecycleStepKind
    depends_on: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    target: str | None = None
    budget: FeedbackBudget = FeedbackBudget()
    protects_qwen: bool = False

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
    def __init__(self, *, root: Path, receipt_path: Path) -> None:
        self._root = root.resolve()
        self._receipt_path = receipt_path.resolve()
        self._receipt_path.relative_to(self._root)

    def launch(self, command: tuple[str, ...], *, log_path: str) -> BuildProcessLaunch:
        destination = (self._root / log_path).resolve()
        destination.relative_to(self._root)
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
            item for item in (str(self._root), existing) if item
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
                cwd=self._root,
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
            log_path=destination.relative_to(self._root).as_posix(),
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

    def capture_qwen_identity(self) -> ContainerIdentity: ...


class QwenIdentityGuard:
    def __init__(self, before: ContainerIdentity) -> None:
        self.before = before

    def verify(self, after: ContainerIdentity) -> ActionResult:
        evidence = (self.before.evidence_reference, after.evidence_reference)
        if after == self.before:
            return ActionResult(
                status=FeedbackStatus.PASSED,
                progress_summary="Qwen identity remained unchanged",
                evidence_refs=evidence,
                next_action="continue lifecycle plan",
            )
        return ActionResult(
            status=FeedbackStatus.BLOCKED,
            progress_summary="Qwen container ID, image, or StartedAt changed",
            evidence_refs=evidence,
            failure_fingerprint=hashlib.sha256(
                f"qwen-identity-drift:{self.before}:{after}".encode()
            ).hexdigest(),
            next_action="stop lifecycle plan and inspect Qwen identity drift",
        )


class QwenIdentityStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write(
        self,
        run_id: str,
        phase: Literal["before", "after"],
        identity: ContainerIdentity,
    ) -> Path:
        validate_identifier(run_id)
        path = self.root / run_id / f"qwen-identity-{phase}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(identity.model_dump(mode="json"), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def read(
        self,
        run_id: str,
        phase: Literal["before", "after"],
    ) -> ContainerIdentity:
        validate_identifier(run_id)
        path = self.root / run_id / f"qwen-identity-{phase}.json"
        return ContainerIdentity.model_validate_json(path.read_text(encoding="utf-8"))


class LifecycleStepExecutor:
    def __init__(
        self,
        *,
        driver: LifecycleDriver,
        qwen_store: QwenIdentityStore,
        run_id: str,
        build_controller: BuildStepController | None = None,
    ) -> None:
        validate_identifier(run_id)
        self._driver = driver
        self._qwen_store = qwen_store
        self._run_id = run_id
        self._build_controller = build_controller

    def run(self, step: LifecycleStepContract, *, now: datetime) -> ActionResult:
        if step.kind is LifecycleStepKind.BUILD:
            if self._build_controller is None:
                raise RuntimeError("build lifecycle step requires a BuildStepController")
            return self._build_controller.run(now=now)
        if step.kind is LifecycleStepKind.CAPTURE_QWEN:
            identity = self._driver.capture_qwen_identity()
            path = self._qwen_store.write(self._run_id, "before", identity)
            return ActionResult(
                status=FeedbackStatus.PASSED,
                progress_summary="Qwen identity captured before protected lifecycle steps",
                evidence_refs=(path.resolve().as_posix(), identity.evidence_reference),
                next_action="continue protected lifecycle steps",
            )
        if step.kind is LifecycleStepKind.VERIFY_QWEN:
            before = self._qwen_store.read(self._run_id, "before")
            after = self._driver.capture_qwen_identity()
            path = self._qwen_store.write(self._run_id, "after", after)
            result = QwenIdentityGuard(before).verify(after)
            return ActionResult.model_validate(
                {
                    **result.model_dump(mode="python"),
                    "evidence_refs": (*result.evidence_refs, path.resolve().as_posix()),
                }
            )
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
            ("qwen-preflight", LifecycleStepKind.COMMAND, ("qwen-preflight",), None),
            ("qwen-identity-before", LifecycleStepKind.CAPTURE_QWEN, (), None),
            ("host-tts-readiness", LifecycleStepKind.COMMAND, ("host-tts-ready",), None),
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
            (
                "qwen-log-check",
                LifecycleStepKind.LOG_CHECK,
                ("docker", "compose", "-f", "docker-compose.qwen.yml", "logs", "qwen-tts"),
                None,
            ),
            ("qwen-identity-after", LifecycleStepKind.VERIFY_QWEN, (), None),
        )
    elif operation == "anima-down":
        definitions = (
            ("qwen-identity-before", LifecycleStepKind.CAPTURE_QWEN, (), None),
            (
                "animetta-cleanup",
                LifecycleStepKind.COMMAND,
                ("docker", "compose", "down", "--remove-orphans"),
                None,
            ),
            ("qwen-identity-after", LifecycleStepKind.VERIFY_QWEN, (), None),
        )
    elif operation == "qwen-up":
        definitions = (
            (
                "qwen-start",
                LifecycleStepKind.COMMAND,
                (
                    "docker",
                    "compose",
                    "-f",
                    "docker-compose.qwen.yml",
                    "up",
                    "-d",
                    "--no-build",
                    "--no-recreate",
                    "qwen-tts",
                ),
                None,
            ),
            ("qwen-preflight", LifecycleStepKind.COMMAND, ("qwen-preflight",), None),
        )
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
                protects_qwen=step_id.startswith("qwen-identity"),
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
