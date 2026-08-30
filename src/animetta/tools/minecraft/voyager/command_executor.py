"""Single authorized Python caller for state-changing GameBot v2 capabilities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate as validate_json

from animetta.tools.gamebot.contracts.v2 import (
    ActionInspectionRequest,
    ActionReceipt,
    ActionRequest,
    BudgetVector,
    CancellationRequest,
    Observation,
    ObservationRequest,
    ReceiptOutcome,
    ReconciliationStatus,
    canonical_json_hash,
)
from animetta.tools.gamebot.runtime import GameBotRuntimeV2

from .budget import (
    BudgetAccount,
    BudgetContractViolationError,
    BudgetUsage,
    budget_usage_from_vector,
)
from .command_models import CommandState, ControlPlaneError
from .journal import CommandJournal, JournalCommand, StepRecord
from .public_activity import PublicActivityProgress, PublicActivityRecorder
from .reconciliation import RecoveryDecision, RecoveryEvidence, decide_recovery
from .strategies.base import ExecuteStep


class ExecutorError(RuntimeError):
    def __init__(self, error: ControlPlaneError) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


@dataclass(frozen=True)
class StepExecutionResult:
    receipt: Any
    after: Observation
    account: BudgetAccount


@dataclass(frozen=True)
class ReconciliationResult:
    decision: RecoveryDecision
    details: dict[str, Any]
    receipt: ActionReceipt | None = None
    observation: Observation | None = None


def _error(
    code: str,
    message: str,
    *,
    phase: str,
    outcome_known: bool = True,
    world_may_have_changed: bool = False,
    caller_may_resubmit: bool = False,
    operator_action: str = "inspect command status",
    details: dict[str, Any] | None = None,
) -> ExecutorError:
    return ExecutorError(
        ControlPlaneError(
            code=code,
            message=message,
            phase=phase,
            outcome_known=outcome_known,
            world_may_have_changed=world_may_have_changed,
            caller_may_resubmit=caller_may_resubmit,
            operator_action=operator_action,
            details=details or {},
        )
    )


def _runtime_budget(account: BudgetAccount) -> BudgetVector:
    remaining = account.remaining
    return BudgetVector(
        max_actions=remaining.max_actions,
        max_strategy_attempts=remaining.max_strategy_attempts,
        max_travel_distance=remaining.max_travel_distance,
        max_blocks_changed=remaining.max_blocks_changed,
        max_damage_taken=remaining.max_damage_taken,
        protected_items=tuple(sorted(remaining.protected_items)),
        resource_consumption=remaining.resource_consumption,
    )


def _receipt_usage(receipt: Any) -> BudgetUsage:
    return budget_usage_from_vector(receipt.budget_usage)


_GROUNDED_VERTICAL_VELOCITY_MIN = -0.09
_SETTLED_VERTICAL_VELOCITY_MAX = 0.01


class CommandExecutor:
    def __init__(
        self,
        *,
        runtime: GameBotRuntimeV2,
        repository: CommandJournal,
        now_ms: Callable[[], int],
        make_id: Callable[[str], str],
        reconciliation_grace_seconds: float = 10.0,
        reconciliation_poll_seconds: float = 0.1,
        activity_recorder: PublicActivityRecorder | None = None,
    ) -> None:
        self._runtime = runtime
        self._repository = repository
        self._now_ms = now_ms
        self._make_id = make_id
        self._reconciliation_grace_seconds = reconciliation_grace_seconds
        self._reconciliation_poll_seconds = reconciliation_poll_seconds
        self._activity_recorder = activity_recorder
        self._dispatch_observer: Callable[[str, str], None] | None = None

    def set_dispatch_observer(self, observer: Callable[[str, str], None]) -> None:
        self._dispatch_observer = observer

    @staticmethod
    def _usage_within_reservation(receipt: Any, step: StepRecord) -> bool:
        actual = _receipt_usage(receipt)
        reserved = BudgetUsage.model_validate(step.reservation)
        scalar_fields = (
            "max_actions",
            "max_strategy_attempts",
            "max_travel_distance",
            "max_blocks_changed",
            "max_damage_taken",
        )
        if any(getattr(actual, field) > getattr(reserved, field) for field in scalar_fields):
            return False
        return all(
            amount <= reserved.resource_consumption.get(name, 0)
            for name, amount in actual.resource_consumption.items()
        )

    async def _reconciled_budget_snapshot(
        self,
        *,
        command_id: str,
        current_step_id: str,
        current_receipt: ActionReceipt,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        """Rebuild cumulative usage from durable receipts without replaying work."""

        settled = BudgetUsage()
        reserved = BudgetUsage()
        for persisted in await self._repository.list_steps(command_id):  # type: ignore[attr-defined]
            if persisted.step_id == current_step_id:
                settled = settled.plus(_receipt_usage(current_receipt))
                continue
            if persisted.state == "settled" and persisted.receipt is not None:
                settled = settled.plus(
                    _receipt_usage(ActionReceipt.model_validate(persisted.receipt))
                )
                continue
            if persisted.state in {"reserved", "dispatched", "unknown"}:
                reserved = reserved.plus(BudgetUsage.model_validate(persisted.reservation))
        return settled, reserved

    @staticmethod
    def _durable_observable_state(observation: Observation) -> dict[str, Any]:
        environment = observation.environment
        durable_environment = {
            key: environment[key] for key in ("blocks", "dimension") if key in environment
        }
        return {
            "position": (
                observation.position.model_dump(mode="json")
                if observation.position is not None
                else None
            ),
            "health": observation.health,
            "food": observation.food,
            "inventory": observation.inventory,
            "equipment": observation.equipment,
            "environment": durable_environment,
        }

    @staticmethod
    def _observation_motion_settled(observation: Observation) -> bool:
        if observation.environment.get("on_ground") is False:
            return False
        velocity = observation.environment.get("velocity")
        if not isinstance(velocity, dict):
            return True
        vertical = velocity.get("y")
        if not isinstance(vertical, int | float):
            return True
        if observation.environment.get("on_ground") is True:
            return (
                _GROUNDED_VERTICAL_VELOCITY_MIN <= float(vertical) <= _SETTLED_VERTICAL_VELOCITY_MAX
            )
        return abs(float(vertical)) <= _SETTLED_VERTICAL_VELOCITY_MAX

    @classmethod
    def _mutations_explain_observation(cls, receipt: Any, observation: Observation) -> bool:
        markers = [
            mutation
            for mutation in receipt.explained_mutations
            if mutation.kind == "other" and mutation.subject == "observable_state"
        ]
        if len(markers) != 1:
            return False
        details = markers[0].details
        before_state = details.get("before_state")
        after_state = details.get("after_state")
        before_hash = details.get("before_state_hash")
        after_hash = details.get("after_state_hash")
        if not isinstance(before_state, dict) or not isinstance(after_state, dict):
            return False
        if before_hash != canonical_json_hash(before_state):
            return False
        if after_hash != canonical_json_hash(after_state):
            return False
        fresh_state = cls._durable_observable_state(observation)
        return fresh_state == after_state and canonical_json_hash(fresh_state) == after_hash

    @classmethod
    def _observable_state_diff(
        cls, receipt: Any, observation: Observation
    ) -> dict[str, dict[str, Any]]:
        """Return the exact durable fields that diverged from a terminal receipt."""

        markers = [
            mutation
            for mutation in receipt.explained_mutations
            if mutation.kind == "other" and mutation.subject == "observable_state"
        ]
        if len(markers) != 1:
            return {}
        receipt_after = markers[0].details.get("after_state")
        if not isinstance(receipt_after, dict):
            return {}
        fresh_state = cls._durable_observable_state(observation)
        return {
            field: {
                "receipt_after": receipt_after.get(field),
                "fresh_observation": fresh_state.get(field),
            }
            for field in sorted(set(receipt_after) | set(fresh_state))
            if receipt_after.get(field) != fresh_state.get(field)
        }

    @staticmethod
    def _recovery_receipt_valid(receipt: Any, step: StepRecord) -> bool:
        expected = {
            "command_id": step.command_id,
            "step_id": step.step_id,
            "correlation_id": step.correlation_id,
            "runtime_instance_id": step.runtime_instance_id,
            "capability": step.capability,
            "parameter_hash": step.params_hash,
        }
        if any(getattr(receipt, field) != value for field, value in expected.items()):
            return False
        return (
            canonical_json_hash(receipt.model_dump(mode="json", exclude={"content_hash"}))
            == receipt.content_hash
        )

    async def reconcile_unknown(
        self, *, command: JournalCommand, error: ControlPlaneError
    ) -> ReconciliationResult:
        """Inspect one persisted correlation without ever replaying its mutation."""

        step_id = error.details.get("step_id")
        correlation_id = error.details.get("correlation_id")
        if not isinstance(step_id, str) or not isinstance(correlation_id, str):
            details = {"reason": "missing persisted step identity", **error.details}
            await self._repository.append_recovery(command.command_id, details)  # type: ignore[attr-defined]
            return ReconciliationResult(RecoveryDecision.BLOCKED_UNKNOWN, details)
        step = await self._repository.get_step(step_id)  # type: ignore[attr-defined]
        if step is None or step.correlation_id != correlation_id:
            details = {"reason": "persisted step not found", **error.details}
            await self._repository.append_recovery(command.command_id, details)  # type: ignore[attr-defined]
            return ReconciliationResult(RecoveryDecision.BLOCKED_UNKNOWN, details)

        try:
            manifest = await self._runtime.get_manifest()
            same_instance = manifest.runtime_instance_id == step.runtime_instance_id
            if not same_instance:
                evidence = RecoveryEvidence(same_instance=False, inspection_state="not_found")
                decision = decide_recovery(evidence)
                details = {
                    "step_id": step_id,
                    "correlation_id": correlation_id,
                    "decision": decision.value,
                    "runtime_instance_id": manifest.runtime_instance_id,
                    "expected_runtime_instance_id": step.runtime_instance_id,
                }
                await self._repository.append_recovery(command.command_id, details)  # type: ignore[attr-defined]
                return ReconciliationResult(decision, details)

            inspection_request = ActionInspectionRequest(
                runtime_instance_id=step.runtime_instance_id,
                correlation_id=correlation_id,
            )
            status = await self._runtime.inspect_action(inspection_request)
            if status.state.value in {"accepted", "running"}:
                await self._runtime.cancel_action(
                    CancellationRequest(
                        runtime_instance_id=step.runtime_instance_id,
                        correlation_id=correlation_id,
                        reason="bounded automatic reconciliation",
                    )
                )
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self._reconciliation_grace_seconds
                while status.state.value in {"accepted", "running"} and loop.time() < deadline:
                    await asyncio.sleep(
                        min(self._reconciliation_poll_seconds, max(0.0, deadline - loop.time()))
                    )
                    status = await self._runtime.inspect_action(inspection_request)

            health = await self._runtime.health()
            receipt = status.receipt
            loop = asyncio.get_running_loop()
            observation_deadline = loop.time() + self._reconciliation_grace_seconds
            observation_attempt = 0
            while True:
                observation_attempt += 1
                observation = await self._runtime.observe(
                    ObservationRequest(
                        transport_id=self._make_id("transport"),
                        command_id=command.command_id,
                        step_id=step.step_id,
                        correlation_id=(f"{correlation_id}:reconcile:{observation_attempt}"),
                        runtime_instance_id=step.runtime_instance_id,
                        deadline_ms=self._now_ms() + 5_000,
                    )
                )
                if self._observation_motion_settled(observation):
                    break
                if loop.time() >= observation_deadline:
                    break
                await asyncio.sleep(
                    min(
                        self._reconciliation_poll_seconds,
                        max(0.0, observation_deadline - loop.time()),
                    )
                )
            receipt_valid = receipt is not None and self._recovery_receipt_valid(receipt, step)
            usage_within = receipt is not None and self._usage_within_reservation(receipt, step)
            evidence = RecoveryEvidence(
                same_instance=True,
                inspection_state=status.state.value,
                receipt_outcome=receipt.outcome.value if receipt is not None else None,
                receipt_reconciliation=(
                    receipt.reconciliation.value if receipt is not None else "accepted"
                ),
                receipt_valid=receipt_valid,
                usage_within_reservation=usage_within,
                idle=not health.busy and health.active_correlation_id is None,
                observation_fresh=(
                    observation.runtime_instance_id == step.runtime_instance_id
                    and (receipt is None or observation.action_sequence >= receipt.action_sequence)
                ),
                observation_stable=self._observation_motion_settled(observation),
                mutations_explained=(
                    receipt is not None
                    and self._mutations_explain_observation(receipt, observation)
                ),
                retention_guarantee_intact=(
                    status.retained_until_ms is not None
                    and status.retained_until_ms >= self._now_ms()
                ),
                action_was_accepted=step.state in {"dispatched", "unknown", "settled"},
            )
            decision = decide_recovery(evidence)
            details = {
                "step_id": step_id,
                "correlation_id": correlation_id,
                "decision": decision.value,
                "inspection_state": status.state.value,
                "idle": evidence.idle,
                "observation_fresh": evidence.observation_fresh,
                "observation_stable": evidence.observation_stable,
                "receipt_valid": evidence.receipt_valid,
                "receipt_reconciliation": evidence.receipt_reconciliation,
                "usage_within_reservation": evidence.usage_within_reservation,
                "mutations_explained": evidence.mutations_explained,
            }
            if receipt is not None and not evidence.mutations_explained:
                details.update(
                    {
                        "rejected_receipt": receipt.model_dump(mode="json"),
                        "fresh_observation": observation.model_dump(mode="json"),
                        "observable_state_diff": self._observable_state_diff(receipt, observation),
                    }
                )
            if receipt is not None and decision in {
                RecoveryDecision.SUCCEEDED_RECONCILED,
                RecoveryDecision.FAILED_RECONCILED,
                RecoveryDecision.CANCELLED_RECONCILED,
            }:
                settled_usage, reserved_usage = await self._reconciled_budget_snapshot(
                    command_id=command.command_id,
                    current_step_id=step_id,
                    current_receipt=receipt,
                )
                await self._repository.settle_step(  # type: ignore[attr-defined]
                    step_id,
                    receipt.model_dump(mode="json"),
                    settled_usage=settled_usage.model_dump(mode="json"),
                    reserved_usage=reserved_usage.model_dump(mode="json"),
                )
            await self._repository.append_recovery(command.command_id, details)  # type: ignore[attr-defined]
            return ReconciliationResult(
                decision,
                details,
                receipt=receipt,
                observation=observation,
            )
        except Exception as exc:
            details = {
                "step_id": step_id,
                "correlation_id": correlation_id,
                "decision": RecoveryDecision.BLOCKED_UNKNOWN.value,
                "reconciliation_error": type(exc).__name__,
                "message": str(exc),
            }
            await self._repository.append_recovery(command.command_id, details)  # type: ignore[attr-defined]
            return ReconciliationResult(RecoveryDecision.BLOCKED_UNKNOWN, details)

    async def execute_step(
        self,
        *,
        command: JournalCommand,
        step: ExecuteStep,
        before: Observation,
        ordinal: int,
        strategy_state_hash: str,
        account: BudgetAccount,
        previous_receipt_hash: str = "",
    ) -> StepExecutionResult:
        if command.state is not CommandState.RUNNING:
            raise _error(
                "COMMAND_NOT_RUNNING",
                "Only the active running command may dispatch runtime work",
                phase="admission",
            )
        if command.cancel_requested_at_ms is not None:
            raise _error(
                "CANCELLATION_REQUESTED",
                "Cancellation was requested before step dispatch",
                phase="admission",
            )
        now = self._now_ms()
        if command.execution_deadline_ms is not None and now >= command.execution_deadline_ms:
            raise _error(
                "EXECUTION_DEADLINE_EXPIRED",
                "Command execution deadline expired before step dispatch",
                phase="budget",
            )

        manifest = await self._runtime.get_manifest()
        try:
            capability = manifest.capability(step.capability)
        except KeyError as exc:
            raise _error(
                "CAPABILITY_NOT_AUTHORIZED",
                f"Manifest does not authorize {step.capability}",
                phase="policy",
            ) from exc
        try:
            validate_json(step.parameters, capability.parameters_schema)
        except JSONSchemaValidationError as exc:
            raise _error(
                "INVALID_CAPABILITY_PARAMETERS",
                exc.message,
                phase="request",
            ) from exc
        if before.runtime_instance_id != manifest.runtime_instance_id:
            raise _error(
                "RUNTIME_INSTANCE_CHANGED",
                "Initial observation belongs to another runtime instance",
                phase="recovery",
                outcome_known=False,
                operator_action="reconcile the command against the active runtime",
            )

        step_id = self._make_id("step")
        correlation_id = self._make_id("correlation")
        try:
            reserved_account = account.reserve(step_id, step.maximum_cost)
        except ValueError as exc:
            raise _error(
                "BUDGET_EXHAUSTED",
                str(exc),
                phase="budget",
            ) from exc
        params_hash = canonical_json_hash(step.parameters)
        step_record = StepRecord(
            step_id=step_id,
            command_id=command.command_id,
            ordinal=ordinal,
            strategy_state_hash=strategy_state_hash,
            capability=step.capability,
            params_hash=params_hash,
            params=step.parameters,
            correlation_id=correlation_id,
            runtime_instance_id=manifest.runtime_instance_id,
            state="reserved",
            reservation=step.maximum_cost.model_dump(mode="json"),
            before_observation_hash=before.content_hash,
        )
        await self._repository.reserve_step(step_record)  # type: ignore[attr-defined]
        if self._activity_recorder is not None:
            await self._activity_recorder.record_command(
                command,
                source_key=f"{step_id}:committed",
                phase="committed",
            )
        request = ActionRequest(
            transport_id=self._make_id("transport"),
            command_id=command.command_id,
            step_id=step_id,
            correlation_id=correlation_id,
            runtime_instance_id=manifest.runtime_instance_id,
            capability=step.capability,
            parameters=step.parameters,
            remaining_budget=_runtime_budget(account),
            deadline_ms=command.execution_deadline_ms or now + 60_000,
            previous_receipt_hash=previous_receipt_hash,
        )
        await self._repository.update_step_state(step_id, "dispatched")  # type: ignore[attr-defined]
        if self._activity_recorder is not None:
            await self._activity_recorder.record_command(
                command,
                source_key=f"{step_id}:acting",
                phase="acting",
            )
        if self._dispatch_observer is not None:
            self._dispatch_observer(command.command_id, correlation_id)
        try:
            receipt = await self._runtime.execute_action(
                request,
                timeout=max(
                    0.001,
                    (request.deadline_ms - now) / 1000 + self._reconciliation_grace_seconds,
                ),
            )
        except Exception as exc:
            await self._repository.update_step_state(step_id, "unknown")  # type: ignore[attr-defined]
            raise _error(
                "RUNTIME_RESPONSE_LOST",
                str(exc),
                phase="recovery",
                outcome_known=False,
                world_may_have_changed=True,
                operator_action="inspect the persisted runtime correlation; do not replay",
                details={"step_id": step_id, "correlation_id": correlation_id},
            ) from exc

        expected = {
            "command_id": command.command_id,
            "step_id": step_id,
            "correlation_id": correlation_id,
            "runtime_instance_id": manifest.runtime_instance_id,
            "capability": step.capability,
            "parameter_hash": params_hash,
        }
        if previous_receipt_hash:
            expected["previous_receipt_hash"] = previous_receipt_hash
        mismatches = {
            field: {"expected": value, "actual": getattr(receipt, field)}
            for field, value in expected.items()
            if getattr(receipt, field) != value
        }
        computed_hash = canonical_json_hash(
            receipt.model_dump(mode="json", exclude={"content_hash"})
        )
        if computed_hash != receipt.content_hash:
            mismatches["content_hash"] = {
                "expected": computed_hash,
                "actual": receipt.content_hash,
            }
        if mismatches:
            await self._repository.update_step_state(step_id, "unknown")  # type: ignore[attr-defined]
            raise _error(
                "INVALID_ACTION_RECEIPT",
                "Runtime receipt identity or hash chain is invalid",
                phase="verification",
                outcome_known=False,
                world_may_have_changed=True,
                operator_action="quarantine runtime and reconcile persisted correlation",
                details={
                    "step_id": step_id,
                    "correlation_id": correlation_id,
                    "mismatches": mismatches,
                },
            )
        try:
            settled_account = reserved_account.settle(step_id, _receipt_usage(receipt))
        except BudgetContractViolationError as exc:
            await self._repository.update_step_state(step_id, "unknown")  # type: ignore[attr-defined]
            raise _error(
                "BUDGET_CONTRACT_VIOLATION",
                str(exc),
                phase="verification",
                outcome_known=False,
                world_may_have_changed=True,
                operator_action="quarantine runtime and reconcile budget usage",
                details={"step_id": step_id, "correlation_id": correlation_id},
            ) from exc

        await self._repository.record_step_receipt(  # type: ignore[attr-defined]
            step_id, receipt.model_dump(mode="json")
        )
        if self._activity_recorder is not None:
            await self._activity_recorder.record_command(
                command,
                source_key=f"{step_id}:checking",
                phase="checking",
            )

        if receipt.reconciliation is not ReconciliationStatus.ACCEPTED:
            await self._repository.update_step_state(step_id, "unknown")  # type: ignore[attr-defined]
            reconciliation_error = receipt.reconciliation_error
            raise _error(
                (
                    "POST_ACTION_RECONCILIATION_PENDING"
                    if receipt.reconciliation is ReconciliationStatus.PENDING
                    else "POST_ACTION_RECONCILIATION_QUARANTINED"
                ),
                (
                    reconciliation_error.message
                    if reconciliation_error is not None
                    else "Runtime evidence is not accepted for mission progression"
                ),
                phase="reconciliation",
                outcome_known=False,
                world_may_have_changed=True,
                operator_action=(
                    reconciliation_error.operator_action
                    if reconciliation_error is not None
                    else "inspect settlement evidence before resuming"
                ),
                details={
                    "step_id": step_id,
                    "correlation_id": correlation_id,
                    "action_outcome": receipt.outcome.value,
                    "post_observation": receipt.post_observation.value,
                    "reconciliation": receipt.reconciliation.value,
                    "goal_verification": receipt.goal_verification.value,
                    "settlement_trace": [
                        sample.model_dump(mode="json") for sample in receipt.settlement_trace
                    ],
                    "reconciliation_error": (
                        reconciliation_error.model_dump(mode="json")
                        if reconciliation_error is not None
                        else None
                    ),
                },
            )

        observation_request = ObservationRequest(
            transport_id=self._make_id("transport"),
            command_id=command.command_id,
            step_id=step_id,
            correlation_id=f"{correlation_id}:post",
            runtime_instance_id=manifest.runtime_instance_id,
            deadline_ms=request.deadline_ms,
        )
        after = await self._runtime.observe(observation_request)
        if (
            after.runtime_instance_id != manifest.runtime_instance_id
            or after.action_sequence < receipt.action_sequence
        ):
            await self._repository.update_step_state(step_id, "unknown")  # type: ignore[attr-defined]
            raise _error(
                "STALE_POST_ACTION_OBSERVATION",
                "Post-action observation is not attributable after the receipt",
                phase="verification",
                outcome_known=False,
                world_may_have_changed=True,
                operator_action="obtain fresh evidence and reconcile",
                details={"step_id": step_id, "correlation_id": correlation_id},
            )
        if not self._mutations_explain_observation(receipt, after):
            await self._repository.update_step_state(step_id, "unknown")  # type: ignore[attr-defined]
            raise _error(
                "UNEXPLAINED_STATE_DELTA",
                "Post-action durable state is not covered by the runtime receipt",
                phase="verification",
                outcome_known=False,
                world_may_have_changed=True,
                operator_action="quarantine runtime and reconcile persisted evidence",
                details={"step_id": step_id, "correlation_id": correlation_id},
            )
        await self._repository.settle_step(  # type: ignore[attr-defined]
            step_id,
            receipt.model_dump(mode="json"),
            settled_usage=settled_account.used.model_dump(mode="json"),
            reserved_usage=settled_account.reserved.model_dump(mode="json"),
        )
        await self._repository.append_checkpoint(  # type: ignore[attr-defined]
            command.command_id,
            {
                "step_id": step_id,
                "ordinal": ordinal,
                "strategy_state_hash": strategy_state_hash,
                "observation_hash": after.content_hash,
                "receipt_hash": receipt.content_hash,
                "runtime_instance_id": manifest.runtime_instance_id,
            },
        )
        if self._activity_recorder is not None:
            total_actions = command.effective_budget.get("max_actions")
            progress = (
                PublicActivityProgress(
                    current=ordinal,
                    total=int(total_actions),
                    unit="actions",
                )
                if isinstance(total_actions, int) and total_actions >= ordinal
                else None
            )
            await self._activity_recorder.record_command(
                command,
                source_key=f"{step_id}:settled",
                phase="checking",
                progress=progress,
            )
        if receipt.outcome is ReceiptOutcome.CANCELLED:
            raise _error(
                "CANCELLATION_REQUESTED",
                "Runtime action was cooperatively cancelled",
                phase="execution",
                details={"step_id": step_id, "correlation_id": correlation_id},
            )
        if receipt.outcome in {ReceiptOutcome.ERROR, ReceiptOutcome.UNKNOWN}:
            runtime_error = receipt.error
            raise _error(
                runtime_error.code if runtime_error is not None else "RUNTIME_OUTCOME_UNKNOWN",
                runtime_error.message
                if runtime_error is not None
                else "Runtime outcome is unknown",
                phase="execution",
                outcome_known=(
                    runtime_error.outcome_known
                    if runtime_error is not None
                    else receipt.outcome is not ReceiptOutcome.UNKNOWN
                ),
                world_may_have_changed=(
                    runtime_error.world_may_have_changed
                    if runtime_error is not None
                    else receipt.outcome is ReceiptOutcome.UNKNOWN
                ),
                caller_may_resubmit=(
                    runtime_error.caller_may_resubmit if runtime_error is not None else False
                ),
                operator_action=(
                    runtime_error.operator_action
                    if runtime_error is not None
                    else "inspect command status"
                ),
                details={"step_id": step_id, "correlation_id": correlation_id},
            )
        return StepExecutionResult(
            receipt=receipt,
            after=after,
            account=settled_account,
        )

    @staticmethod
    def verify_completion(
        *, verifier: Any, goal: Any, strategy_complete: bool, evidence: list[Any]
    ) -> dict[str, Any]:
        del strategy_complete
        return verifier.verify(goal=goal, evidence=evidence)
