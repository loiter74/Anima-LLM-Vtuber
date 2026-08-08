from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from scripts import runtime_lifecycle
from tooling.execution_feedback import (
    FeedbackStatus,
    IterationPlanStore,
    LeaseManager,
    ResourceIdentity,
    ResourceKind,
    ResourceObservation,
)
from tooling.execution_feedback.lifecycle import (
    BuildProcessLaunch,
    BuildStepController,
    LeasedSubprocessBuildDriver,
    LifecycleDriverObservation,
    LifecycleStepExecutor,
    LifecycleStepKind,
    freeze_lifecycle_plan,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


class FakeBuildDriver:
    def __init__(self) -> None:
        self.launches = 0
        self.running = True
        self.exit_code: int | None = None
        self.identity = ResourceIdentity(
            kind=ResourceKind.PROCESS,
            resource_id="4242",
            creation_token="2026-08-08T10:00:00Z",
        )

    def launch(self, command: tuple[str, ...], *, log_path: str) -> BuildProcessLaunch:
        assert command == ("docker", "compose", "build", "animetta")
        assert log_path.endswith("animetta-build.log")
        self.launches += 1
        return BuildProcessLaunch(identity=self.identity, log_path=log_path)

    def inspect(self, identity: ResourceIdentity) -> ResourceObservation:
        assert identity == self.identity
        return ResourceObservation(
            identity=self.identity,
            running=self.running,
            exit_code=self.exit_code,
        )


class FakeLifecycleDriver:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.http_targets: list[str] = []
        self.log_commands: list[tuple[str, ...]] = []

    def run_command(self, command: tuple[str, ...], *, timeout_seconds: float):
        assert timeout_seconds <= 240
        self.commands.append(command)
        return LifecycleDriverObservation(
            succeeded=True,
            summary="command passed",
            evidence_refs=(f"command:{len(self.commands)}",),
            exit_code=0,
        )

    def check_http(self, target: str, *, timeout_seconds: float):
        assert timeout_seconds <= 240
        self.http_targets.append(target)
        return LifecycleDriverObservation(
            succeeded=True,
            summary="HTTP 200",
            evidence_refs=(f"http:{target}",),
            exit_code=0,
        )

    def check_logs(self, command: tuple[str, ...], *, timeout_seconds: float):
        assert timeout_seconds <= 240
        self.log_commands.append(command)
        return LifecycleDriverObservation(
            succeeded=True,
            summary="logs clean",
            evidence_refs=(f"logs:{len(self.log_commands)}",),
            exit_code=0,
        )


def test_anima_feedback_plan_contains_every_protocol_stage_under_its_own_step() -> None:
    lifecycle = freeze_lifecycle_plan("anima-up", input_fingerprint="a" * 64)

    assert tuple(step.id for step in lifecycle.steps) == (
        "host-tts-start",
        "host-tts-preflight",
        "animetta-build",
        "animetta-start",
        "animetta-health",
        "frontend-readiness",
        "default-log-check",
    )
    assert tuple(step.kind for step in lifecycle.steps) == (
        LifecycleStepKind.COMMAND,
        LifecycleStepKind.COMMAND,
        LifecycleStepKind.BUILD,
        LifecycleStepKind.COMMAND,
        LifecycleStepKind.HTTP_CHECK,
        LifecycleStepKind.HTTP_CHECK,
        LifecycleStepKind.LOG_CHECK,
    )
    assert all(step.budget.deadline_seconds <= 300 for step in lifecycle.plan.steps)
    assert all(
        step.depends_on == (() if index == 0 else (lifecycle.steps[index - 1].id,))
        for index, step in enumerate(lifecycle.steps)
    )


def test_cleanup_is_one_bounded_animetta_action() -> None:
    lifecycle = freeze_lifecycle_plan("anima-down", input_fingerprint="a" * 64)

    assert tuple(step.id for step in lifecycle.steps) == ("animetta-cleanup",)
    cleanup = lifecycle.steps[0]
    assert cleanup.command == ("docker", "compose", "down", "--remove-orphans")
    assert cleanup.budget.action_seconds == 240


def test_host_tts_operations_have_bounded_plans() -> None:
    expected_steps = {
        "host-tts-up": ("host-tts-start", "host-tts-preflight"),
        "host-tts-status": ("host-tts-status",),
        "host-tts-stop": ("host-tts-stop",),
    }

    for operation, step_ids in expected_steps.items():
        lifecycle = freeze_lifecycle_plan(operation, input_fingerprint="a" * 64)

        assert tuple(step.id for step in lifecycle.steps) == step_ids
        assert all(step.budget.deadline_seconds <= 300 for step in lifecycle.plan.steps)


def test_injected_lifecycle_executor_checks_start_http_and_app_logs(
    tmp_path,
) -> None:
    lifecycle = freeze_lifecycle_plan("anima-up", input_fingerprint="a" * 64)
    driver = FakeLifecycleDriver()
    executor = LifecycleStepExecutor(
        driver=driver,
    )

    results = [
        executor.run(step, now=NOW)
        for step in lifecycle.steps
        if step.kind is not LifecycleStepKind.BUILD
    ]

    assert all(result.status is FeedbackStatus.PASSED for result in results)
    assert ("docker", "compose", "up", "-d", "--no-build", "animetta") in driver.commands
    assert driver.http_targets == ["http://localhost/health", "http://localhost"]
    assert driver.log_commands == [("docker", "compose", "logs", "animetta")]


def test_buildkit_work_is_resumed_from_exact_process_lease_without_duplicate_launch(
    tmp_path,
) -> None:
    driver = FakeBuildDriver()
    store = IterationPlanStore(tmp_path)
    controller = BuildStepController(
        lease_manager=LeaseManager(store),
        driver=driver,
        run_id="run-build",
        owner="lifecycle-worker",
        lease_id="animetta-build",
        command=("docker", "compose", "build", "animetta"),
        command_digest=hashlib.sha256(b"docker compose build animetta").hexdigest(),
        log_path="artifacts/iteration-plans/run-build/animetta-build.log",
    )

    started = controller.run(now=NOW)
    resumed = controller.run(now=NOW + timedelta(seconds=30))

    assert started.status is FeedbackStatus.IN_PROGRESS
    assert resumed.status is FeedbackStatus.IN_PROGRESS
    assert started.lease == resumed.lease
    assert driver.launches == 1
    lease = store.read_lease("run-build", "animetta-build")
    assert lease.identity == driver.identity
    assert lease.log_path.endswith("animetta-build.log")


def test_buildkit_lease_id_is_unique_to_each_lifecycle_run() -> None:
    first = runtime_lifecycle._build_lease_id("anima-up-first")
    second = runtime_lifecycle._build_lease_id("anima-up-second")

    assert first == "anima-up-first-animetta-build"
    assert second == "anima-up-second-animetta-build"
    assert first != second


def test_completed_build_lease_becomes_terminal_evidence(tmp_path) -> None:
    driver = FakeBuildDriver()
    store = IterationPlanStore(tmp_path)
    controller = BuildStepController(
        lease_manager=LeaseManager(store),
        driver=driver,
        run_id="run-build",
        owner="lifecycle-worker",
        lease_id="animetta-build",
        command=("docker", "compose", "build", "animetta"),
        command_digest="b" * 64,
        log_path="artifacts/iteration-plans/run-build/animetta-build.log",
    )
    controller.run(now=NOW)
    driver.running = False
    driver.exit_code = 0

    completed = controller.run(now=NOW + timedelta(seconds=30))

    assert completed.status is FeedbackStatus.PASSED
    assert completed.evidence_refs == ("artifacts/iteration-plans/run-build/animetta-build.log",)
    assert driver.launches == 1


def test_public_lifecycle_command_has_no_migration_switch() -> None:
    args = runtime_lifecycle._parser().parse_args(["anima-up"])

    assert args.operation == "anima-up"
    assert not hasattr(args, "bounded_feedback")


def test_default_command_routes_to_resumable_bounded_operation(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_bounded(operation: str, *, run_id: str, artifacts_root) -> int:
        assert artifacts_root == tmp_path
        calls.append((operation, run_id))
        return 2

    monkeypatch.setattr(runtime_lifecycle, "run_bounded_operation", fake_bounded)

    exit_code = runtime_lifecycle.main(
        [
            "anima-up",
            "--run-id",
            "run-lifecycle",
            "--artifacts-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
    assert calls == [("anima-up", "run-lifecycle")]


def test_system_lifecycle_preflight_targets_host_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    preflight_calls: list[bool] = []

    def fake_preflight(*, wait: bool) -> list[str]:
        preflight_calls.append(wait)
        return ["qwen-probe"]

    def fake_run(command, **kwargs):
        assert command == ("qwen-probe",)
        assert kwargs["timeout"] <= 240
        return runtime_lifecycle.subprocess.CompletedProcess(command, 0, "ready", "")

    monkeypatch.setattr(runtime_lifecycle, "_preflight", fake_preflight)
    monkeypatch.setattr(runtime_lifecycle.subprocess, "run", fake_run)
    driver = runtime_lifecycle._SystemLifecycleDriver(evidence_root=tmp_path)

    result = driver.run_command(("host-tts-preflight",), timeout_seconds=240)

    assert result.succeeded is True
    assert preflight_calls == [False]


def test_build_helper_runs_from_workspace_with_workspace_on_pythonpath(
    monkeypatch,
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 4242

        def terminate(self) -> None:
            raise AssertionError("creation token should be available")

    def fake_popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return FakeProcess()

    monkeypatch.setattr("tooling.execution_feedback.lifecycle.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "tooling.execution_feedback.lifecycle._process_creation_token",
        lambda _pid: "creation-token",
    )
    driver = LeasedSubprocessBuildDriver(
        workspace_root=workspace,
        artifacts_root=artifacts,
        receipt_path=artifacts / "receipt.json",
    )

    launched = driver.launch(("docker", "compose", "build"), log_path="run/build.log")

    assert captured["cwd"] == workspace
    assert str(captured["env"]["PYTHONPATH"]).split(runtime_lifecycle.os.pathsep)[0] == str(
        workspace
    )
    assert launched.log_path == "run/build.log"
