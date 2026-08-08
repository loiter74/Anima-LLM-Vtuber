"""Command-scoped Voyager controller composing strategies and the sole executor."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import TypeAdapter

from animetta.tools.gamebot.contracts.v2 import (
    CancellationRequest,
    ObservationRequest,
)
from animetta.tools.gamebot.runtime import GameBotRuntimeV2

from .budget import BudgetAccount, ExecutionBudget
from .command_executor import CommandExecutor, ExecutorError, ReconciliationResult
from .command_models import CommandResult, CommandState, ControllerState, ControlPlaneError
from .goal_evidence import EmptyGoalEvidenceCollector, GoalEvidenceCollector
from .goal_models import AtomicAction, GoalSpec
from .goal_verifier import GoalVerifier
from .journal import CommandJournal, JournalCommand
from .reconciliation import RecoveryDecision
from .scheduler import CommandExecutionError
from .strategies.atomic import AtomicStrategy
from .strategies.base import Complete, ExecuteStep, StrategyFailure


def execution_budget_from_json(value: dict[str, object]) -> ExecutionBudget:
    """Restore a strict budget through Pydantic's JSON input semantics."""

    return ExecutionBudget.model_validate_json(json.dumps(value, separators=(",", ":")))


def _reconciled_terminal_for_command(
    *,
    command: JournalCommand,
    recovery: ReconciliationResult,
    verifier: GoalVerifier,
) -> CommandState | None:
    terminal = {
        RecoveryDecision.SUCCEEDED_RECONCILED: CommandState.SUCCEEDED_RECONCILED,
        RecoveryDecision.READ_RECONCILED: CommandState.SUCCEEDED_RECONCILED,
        RecoveryDecision.FAILED_RECONCILED: CommandState.FAILED_RECONCILED,
        RecoveryDecision.KNOWN_NO_EFFECT: CommandState.FAILED_RECONCILED,
        RecoveryDecision.CANCELLED_RECONCILED: CommandState.CANCELLED_RECONCILED,
    }.get(recovery.decision)
    if terminal is not CommandState.SUCCEEDED_RECONCILED or command.mode == "atomic":
        return terminal

    goal_payload = command.payload.get("goal")
    if (
        not isinstance(goal_payload, dict)
        or recovery.receipt is None
        or recovery.observation is None
    ):
        return CommandState.FAILED_RECONCILED
    goal: GoalSpec = TypeAdapter(GoalSpec).validate_python(goal_payload)
    verification = verifier.verify(
        goal=goal,
        final=recovery.observation,
        receipts=[recovery.receipt],
    )
    return (
        CommandState.SUCCEEDED_RECONCILED
        if verification["satisfied"]
        else CommandState.FAILED_RECONCILED
    )


class UnifiedVoyagerController:
    """Own active strategy state, cancellation, verification, and quarantine."""

    def __init__(
        self,
        *,
        runtime: GameBotRuntimeV2,
        repository: CommandJournal,
        executor: CommandExecutor,
        strategy_factories: dict[str, Any],
        verifier: GoalVerifier | None = None,
        evidence_collector: GoalEvidenceCollector | None = None,
        on_strategy_complete: Callable[..., Awaitable[None]] | None = None,
        on_strategy_failed: Callable[..., Awaitable[None]] | None = None,
        make_id: Callable[[str], str],
        now_ms: Callable[[], int],
        initial_state: ControllerState = ControllerState.IDLE,
    ) -> None:
        self._runtime = runtime
        self._repository = repository
        self._executor = executor
        self._strategy_factories = strategy_factories
        self._verifier = verifier or GoalVerifier()
        self._evidence_collector = evidence_collector or EmptyGoalEvidenceCollector()
        self._on_strategy_complete = on_strategy_complete
        self._on_strategy_failed = on_strategy_failed
        self._make_id = make_id
        self._now_ms = now_ms
        self.state = initial_state
        self.active_command_id: str | None = None
        self._active_correlation_id: str | None = None
        self._executor.set_dispatch_observer(self._on_dispatch)

    def _on_dispatch(self, command_id: str, correlation_id: str) -> None:
        if command_id == self.active_command_id:
            self._active_correlation_id = correlation_id

    async def execute_command(self, command: JournalCommand) -> None:
        if self.state is ControllerState.QUARANTINED:
            raise RuntimeError("CONTROLLER_QUARANTINED")
        self.state = ControllerState.RUNNING
        self.active_command_id = command.command_id
        try:
            await self._execute_active(command)
        except ExecutorError as exc:
            if not exc.error.outcome_known:
                self.state = ControllerState.RECONCILING
                recovery = await self._executor.reconcile_unknown(command=command, error=exc.error)
                terminal = _reconciled_terminal_for_command(
                    command=command,
                    recovery=recovery,
                    verifier=self._verifier,
                )
                if terminal is not None:
                    goal_verified = not (
                        recovery.decision is RecoveryDecision.SUCCEEDED_RECONCILED
                        and terminal is CommandState.FAILED_RECONCILED
                    )
                    raise CommandExecutionError(
                        terminal_state=terminal,
                        reason_code=(
                            recovery.decision.value.upper()
                            if goal_verified
                            else "GOAL_NOT_VERIFIED_AFTER_RECONCILIATION"
                        ),
                        message=(
                            f"Recovered {recovery.decision.value}"
                            if goal_verified
                            else "Recovered action did not verify the complete goal"
                        ),
                        details={
                            **recovery.details,
                            "recovered_action_decision": recovery.decision.value,
                            "goal_verified": goal_verified,
                        },
                        requires_reconciliation=True,
                    ) from exc
                self.state = ControllerState.QUARANTINED
                error = ControlPlaneError(
                    code=exc.error.code,
                    message=exc.error.message,
                    phase=exc.error.phase,
                    outcome_known=False,
                    world_may_have_changed=True,
                    caller_may_resubmit=False,
                    operator_action="inspect quarantined reconciliation evidence",
                    details=recovery.details,
                )
                terminal_result = CommandResult(
                    command_id=command.command_id,
                    state=CommandState.BLOCKED_UNKNOWN,
                    output={"reconciliation": recovery.details},
                    receipt_ids=(
                        (recovery.receipt.receipt_id,) if recovery.receipt is not None else ()
                    ),
                    error=error,
                ).model_dump(mode="json")
                raise CommandExecutionError(
                    terminal_state=CommandState.BLOCKED_UNKNOWN,
                    reason_code=exc.error.code,
                    message=exc.error.message,
                    details=recovery.details,
                    requires_reconciliation=True,
                    terminal_result=terminal_result,
                ) from exc
            terminal = (
                CommandState.CANCELLED
                if exc.error.code == "CANCELLATION_REQUESTED"
                else CommandState.FAILED
            )
            raise CommandExecutionError(
                terminal_state=terminal,
                reason_code=exc.error.code,
                message=exc.error.message,
                details=exc.error.details,
            ) from exc
        finally:
            if self.state is not ControllerState.QUARANTINED:
                self.state = ControllerState.IDLE
            self.active_command_id = None
            self._active_correlation_id = None

    async def _execute_active(self, command: JournalCommand) -> None:
        manifest = await self._runtime.get_manifest()
        payload = command.payload
        goal = (
            TypeAdapter(GoalSpec).validate_python(payload["goal"]) if payload.get("goal") else None
        )
        if command.mode == "atomic":
            strategy = AtomicStrategy(
                action=AtomicAction.model_validate(payload["action"]), manifest=manifest
            )
        else:
            factory = self._strategy_factories.get(str(command.mode))
            if factory is None:
                raise RuntimeError(f"STRATEGY_NOT_CONFIGURED: {command.mode}")
            strategy = factory(manifest, command)
        state = strategy.prepare(goal)
        account = BudgetAccount(limit=execution_budget_from_json(command.effective_budget))
        observation = await self._runtime.observe(
            ObservationRequest(
                transport_id=self._make_id("transport"),
                command_id=command.command_id,
                step_id="initial-observation",
                correlation_id=self._make_id("correlation"),
                runtime_instance_id=manifest.runtime_instance_id,
                deadline_ms=command.execution_deadline_ms or self._now_ms() + 5_000,
            )
        )
        initial = observation
        receipts = []
        previous_hash = ""
        ordinal = 0
        try:
            while True:
                decision = strategy.propose(state, observation)
                if isinstance(decision, StrategyFailure):
                    raise RuntimeError(f"{decision.code}: {decision.message}")
                if isinstance(decision, Complete):
                    if goal is not None:
                        evidence = await self._evidence_collector.collect(
                            command=command,
                            manifest=manifest,
                            goal=goal,
                            initial=initial,
                            final=observation,
                            receipts=tuple(receipts),
                            output=decision.output,
                        )
                        verification = self._verifier.verify(
                            goal=goal,
                            initial=initial,
                            final=observation,
                            receipts=receipts,
                            **evidence.verifier_arguments(),
                        )
                        if not verification["satisfied"]:
                            error = ControlPlaneError(
                                code="GOAL_VERIFICATION_FAILED",
                                message="Independent goal verification failed",
                                phase="goal_verification",
                                outcome_known=True,
                                world_may_have_changed=bool(receipts),
                                caller_may_resubmit=False,
                                operator_action="inspect predicate results and collected evidence",
                                details={"verification": verification},
                            )
                            terminal_result = CommandResult(
                                command_id=command.command_id,
                                state=CommandState.FAILED,
                                output={
                                    "goal_verification": verification,
                                    "goal_evidence": evidence.model_dump(mode="json"),
                                },
                                receipt_ids=tuple(receipt.receipt_id for receipt in receipts),
                                error=error,
                            ).model_dump(mode="json")
                            raise CommandExecutionError(
                                terminal_state=CommandState.FAILED,
                                reason_code=error.code,
                                message=error.message,
                                details=error.details,
                                terminal_result=terminal_result,
                            )
                    if self._on_strategy_complete is not None:
                        await self._on_strategy_complete(
                            command=command,
                            manifest=manifest,
                            output=decision.output,
                        )
                    return
                if not isinstance(decision, ExecuteStep):
                    raise RuntimeError("INVALID_STRATEGY_DECISION")
                ordinal += 1
                result = await self._executor.execute_step(
                    command=command,
                    step=decision,
                    before=observation,
                    ordinal=ordinal,
                    strategy_state_hash=self._make_id("strategy-state").ljust(64, "0")[:64],
                    account=account,
                    previous_receipt_hash=previous_hash,
                )
                account = result.account
                observation = result.after
                receipts.append(result.receipt)
                previous_hash = result.receipt.content_hash
                state = strategy.accept_result(
                    state,
                    {
                        "outcome": result.receipt.outcome.value,
                        "receipt_hash": result.receipt.content_hash,
                        "command_id": result.receipt.command_id,
                        "correlation_id": result.receipt.correlation_id,
                        "start_state_hash": result.receipt.before_observation_hash,
                        "resource_instance_ref": (
                            result.receipt.explained_mutations[0].subject
                            if result.receipt.explained_mutations
                            else "unattributed"
                        ),
                    },
                )
        except Exception as exc:
            if self._on_strategy_failed is not None:
                with contextlib.suppress(Exception):
                    await self._on_strategy_failed(
                        command=command,
                        manifest=manifest,
                        state=state,
                        error=exc,
                        receipt_hashes=tuple(receipt.content_hash for receipt in receipts),
                    )
            raise

    async def signal_cancel(self, command_id: str) -> str | None:
        if self.state is ControllerState.QUARANTINED:
            command = await self._repository.get_command(command_id)
            step = await self._repository.latest_step(command_id)
            if command is None or command.state is not CommandState.BLOCKED_UNKNOWN or step is None:
                return "RECOVERY_INCOMPLETE"
            self.state = ControllerState.RECONCILING
            reconciling = await self._repository.transition(
                command_id,
                expected_version=command.state_version,
                target=CommandState.RECONCILING,
                reason_code="STOP_RECONCILIATION_RETRY",
                actor="controller",
                occurred_at_ms=self._now_ms(),
            )
            recovery = await self._executor.reconcile_unknown(
                command=reconciling,
                error=ControlPlaneError(
                    code="RECOVERY_RETRY",
                    message="Global stop retried persisted reconciliation",
                    phase="recovery",
                    outcome_known=False,
                    world_may_have_changed=True,
                    caller_may_resubmit=False,
                    operator_action="inspect persisted correlation",
                    details={
                        "step_id": step.step_id,
                        "correlation_id": step.correlation_id,
                    },
                ),
            )
            terminal = _reconciled_terminal_for_command(
                command=command,
                recovery=recovery,
                verifier=self._verifier,
            )
            if terminal is None:
                await self._repository.transition(
                    command_id,
                    expected_version=reconciling.state_version,
                    target=CommandState.BLOCKED_UNKNOWN,
                    reason_code="RECOVERY_INCOMPLETE",
                    actor="controller",
                    occurred_at_ms=self._now_ms(),
                    details=recovery.details,
                )
                self.state = ControllerState.QUARANTINED
                return "RECOVERY_INCOMPLETE"
            goal_verified = not (
                recovery.decision is RecoveryDecision.SUCCEEDED_RECONCILED
                and terminal is CommandState.FAILED_RECONCILED
            )
            await self._repository.transition(
                command_id,
                expected_version=reconciling.state_version,
                target=terminal,
                reason_code=(
                    recovery.decision.value.upper()
                    if goal_verified
                    else "GOAL_NOT_VERIFIED_AFTER_RECONCILIATION"
                ),
                actor="controller",
                occurred_at_ms=self._now_ms(),
                details={
                    **recovery.details,
                    "recovered_action_decision": recovery.decision.value,
                    "goal_verified": goal_verified,
                },
            )
            self.state = ControllerState.IDLE
            return None
        if command_id != self.active_command_id or self._active_correlation_id is None:
            return None
        runtime_id = self._runtime.runtime_instance_id
        if runtime_id is None:
            return None
        await self._runtime.cancel_action(
            CancellationRequest(
                runtime_instance_id=runtime_id,
                correlation_id=self._active_correlation_id,
                reason="global stop",
            )
        )
        return None
