"""Authoritative command-journal protocol and deterministic in-memory store."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .command_models import TERMINAL_COMMAND_STATES, CommandState, validate_transition


class IdempotencyConflictError(ValueError):
    """One caller reused a request identity for different canonical content."""


class StaleCommandVersionError(RuntimeError):
    """A compare-and-swap transition lost its race."""


class QueueCapacityExceededError(RuntimeError):
    """The bounded journal queue cannot admit another execute command."""


class _JournalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CommandDraft(_JournalModel):
    command_id: str
    caller_scope: str
    request_id: str = Field(min_length=1, max_length=128)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str
    mode: str | None = None
    payload: dict[str, Any]
    requested_budget: dict[str, Any]
    effective_budget: dict[str, Any]
    accepted_at_ms: int = Field(ge=0)
    queue_deadline_ms: int | None = Field(default=None, ge=0)
    execution_deadline_ms: int | None = Field(default=None, ge=0)


class JournalCommand(CommandDraft):
    queue_sequence: int = Field(gt=0)
    state: CommandState
    state_version: int = Field(ge=0)
    started_at_ms: int | None = None
    cancel_requested_at_ms: int | None = None
    active_step_id: str | None = None
    runtime_instance_id: str | None = None
    blocked_reason_code: str | None = None
    terminal_at_ms: int | None = None
    terminal_result: dict[str, Any] | None = None


class CommandTransition(_JournalModel):
    transition_id: int = Field(gt=0)
    command_id: str
    from_state: str | None
    to_state: str
    command_version: int = Field(ge=0)
    reason_code: str
    actor: str
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at_ms: int = Field(ge=0)


class ProjectionPage(_JournalModel):
    projection_version: int = Field(ge=0)
    commands: tuple[JournalCommand, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class StartupRecovery:
    interrupted_command_ids: tuple[str, ...]
    blocked_command_ids: tuple[str, ...]
    quarantined: bool


@dataclass(frozen=True)
class StopBarrierCommit:
    stop_command: JournalCommand
    idempotency_reused: bool
    active_command_id: str | None
    cancelled_command_ids: tuple[str, ...]


class StepRecord(_JournalModel):
    step_id: str
    command_id: str
    ordinal: int = Field(gt=0)
    strategy_state_hash: str
    capability: str
    params_hash: str
    params: dict[str, Any]
    correlation_id: str
    runtime_instance_id: str
    state: str
    reservation: dict[str, Any]
    before_observation_hash: str
    receipt: dict[str, Any] | None = None


class CommandJournal(Protocol):
    async def create_command(self, draft: CommandDraft) -> tuple[JournalCommand, bool]: ...

    async def get_command(self, command_id: str) -> JournalCommand | None: ...

    async def latest_step(self, command_id: str) -> StepRecord | None: ...

    async def list_steps(self, command_id: str) -> tuple[StepRecord, ...]: ...

    async def transitions(self, command_id: str) -> list[CommandTransition]: ...

    async def apply_stop_barrier(
        self, draft: CommandDraft, *, occurred_at_ms: int
    ) -> StopBarrierCommit: ...

    async def transition(
        self,
        command_id: str,
        *,
        expected_version: int,
        target: CommandState,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        terminal_result: dict[str, Any] | None = None,
    ) -> JournalCommand: ...


class InMemoryCommandJournal:
    """Lock-linearized journal used for model, scheduler, and fault tests."""

    def __init__(self, *, queue_capacity: int = 100) -> None:
        self._lock = asyncio.Lock()
        self._queue_capacity = queue_capacity
        self._commands: dict[str, JournalCommand] = {}
        self._requests: dict[tuple[str, str], tuple[str, str]] = {}
        self._transitions: list[CommandTransition] = []
        self._sequence = 0
        self._transition_sequence = 0
        self._projection_version = 0
        self._facts: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._steps: dict[str, StepRecord] = {}
        self._accepting_execute = True

    @property
    def projection_version(self) -> int:
        return self._projection_version

    async def begin_shutdown(self, *, occurred_at_ms: int) -> None:
        del occurred_at_ms
        async with self._lock:
            self._accepting_execute = False

    async def create_command(self, draft: CommandDraft) -> tuple[JournalCommand, bool]:
        async with self._lock:
            key = (draft.caller_scope, draft.request_id)
            existing = self._requests.get(key)
            if existing:
                existing_hash, command_id = existing
                if existing_hash != draft.request_hash:
                    raise IdempotencyConflictError("IDEMPOTENCY_CONFLICT")
                return self._commands[command_id].model_copy(deep=True), True
            if draft.kind == "execute" and not self._accepting_execute:
                raise RuntimeError("CONTROLLER_NOT_ACCEPTING_EXECUTE")
            queued = sum(
                command.state is CommandState.QUEUED
                for command in self._commands.values()
                if command.kind == "execute"
            )
            if draft.kind == "execute" and queued >= self._queue_capacity:
                raise QueueCapacityExceededError("QUEUE_CAPACITY_EXCEEDED")
            self._sequence += 1
            command = JournalCommand(
                **draft.model_dump(mode="python"),
                queue_sequence=self._sequence,
                state=CommandState.QUEUED,
                state_version=0,
            )
            self._commands[command.command_id] = command
            self._requests[key] = (draft.request_hash, command.command_id)
            self._facts[command.command_id] = {
                "receipts": [],
                "budgets": [],
                "checkpoints": [],
                "recoveries": [],
            }
            self._append_transition(
                command,
                from_state=None,
                reason_code="ACCEPTED",
                actor="gateway",
                occurred_at_ms=draft.accepted_at_ms,
            )
            self._projection_version += 1
            return command.model_copy(deep=True), False

    def _append_transition(
        self,
        command: JournalCommand,
        *,
        from_state: CommandState | None,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._transition_sequence += 1
        self._transitions.append(
            CommandTransition(
                transition_id=self._transition_sequence,
                command_id=command.command_id,
                from_state=from_state.value if from_state else None,
                to_state=command.state.value,
                command_version=command.state_version,
                reason_code=reason_code,
                actor=actor,
                details=details or {},
                occurred_at_ms=occurred_at_ms,
            )
        )

    async def get_command(self, command_id: str) -> JournalCommand | None:
        async with self._lock:
            command = self._commands.get(command_id)
            return command.model_copy(deep=True) if command else None

    async def find_by_request(self, caller_scope: str, request_id: str) -> JournalCommand | None:
        async with self._lock:
            record = self._requests.get((caller_scope, request_id))
            if record is None:
                return None
            return self._commands[record[1]].model_copy(deep=True)

    async def transition(
        self,
        command_id: str,
        *,
        expected_version: int,
        target: CommandState,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        terminal_result: dict[str, Any] | None = None,
    ) -> JournalCommand:
        async with self._lock:
            command = self._commands[command_id]
            if command.state_version != expected_version:
                raise StaleCommandVersionError(command_id)
            validate_transition(command.state, target)
            updates: dict[str, Any] = {
                "state": target,
                "state_version": expected_version + 1,
            }
            if target is CommandState.RUNNING:
                updates["started_at_ms"] = occurred_at_ms
            if target in TERMINAL_COMMAND_STATES:
                updates["terminal_at_ms"] = occurred_at_ms
                updates["terminal_result"] = terminal_result
            elif terminal_result is not None:
                raise ValueError("terminal_result requires a terminal command state")
            changed = command.model_copy(update=updates, deep=True)
            self._commands[command_id] = changed
            self._append_transition(
                changed,
                from_state=command.state,
                reason_code=reason_code,
                actor=actor,
                occurred_at_ms=occurred_at_ms,
                details=details,
            )
            self._projection_version += 1
            return changed.model_copy(deep=True)

    async def transitions(self, command_id: str) -> list[CommandTransition]:
        async with self._lock:
            return [
                transition.model_copy(deep=True)
                for transition in self._transitions
                if transition.command_id == command_id
            ]

    async def _append_fact(self, command_id: str, kind: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._facts[command_id][kind].append(dict(payload))
            self._projection_version += 1

    async def append_receipt(self, command_id: str, ordinal: int, receipt: dict[str, Any]) -> None:
        await self._append_fact(command_id, "receipts", {"ordinal": ordinal, **receipt})

    async def save_budget(
        self, command_id: str, settled: dict[str, Any], reserved: dict[str, Any]
    ) -> None:
        await self._append_fact(command_id, "budgets", {"settled": settled, "reserved": reserved})

    async def append_checkpoint(self, command_id: str, checkpoint: dict[str, Any]) -> None:
        await self._append_fact(command_id, "checkpoints", checkpoint)

    async def append_recovery(self, command_id: str, recovery: dict[str, Any]) -> None:
        await self._append_fact(command_id, "recoveries", recovery)

    async def command_facts(self, command_id: str) -> dict[str, int]:
        async with self._lock:
            return {kind: len(records) for kind, records in self._facts[command_id].items()}

    async def reserve_step(self, step: StepRecord) -> None:
        async with self._lock:
            if step.step_id in self._steps:
                raise ValueError(f"duplicate step: {step.step_id}")
            if any(
                existing.command_id == step.command_id and existing.ordinal == step.ordinal
                for existing in self._steps.values()
            ):
                raise ValueError(f"duplicate step ordinal: {step.ordinal}")
            if any(
                existing.runtime_instance_id == step.runtime_instance_id
                and existing.correlation_id == step.correlation_id
                for existing in self._steps.values()
            ):
                raise ValueError(f"duplicate correlation: {step.correlation_id}")
            self._steps[step.step_id] = step.model_copy(deep=True)

    async def update_step_state(self, step_id: str, state: str) -> StepRecord:
        async with self._lock:
            current = self._steps[step_id]
            changed = current.model_copy(update={"state": state}, deep=True)
            self._steps[step_id] = changed
            return changed.model_copy(deep=True)

    async def record_step_receipt(self, step_id: str, receipt: dict[str, Any]) -> StepRecord:
        async with self._lock:
            current = self._steps[step_id]
            changed = current.model_copy(update={"receipt": dict(receipt)}, deep=True)
            self._steps[step_id] = changed
            return changed.model_copy(deep=True)

    async def settle_step(
        self,
        step_id: str,
        receipt: dict[str, Any],
        *,
        settled_usage: dict[str, Any] | None = None,
        reserved_usage: dict[str, Any] | None = None,
    ) -> StepRecord:
        async with self._lock:
            current = self._steps[step_id]
            changed = current.model_copy(
                update={"state": "settled", "receipt": dict(receipt)}, deep=True
            )
            self._steps[step_id] = changed
            if settled_usage is not None:
                self._facts[current.command_id]["budgets"].append(
                    {
                        "settled": settled_usage,
                        "reserved": reserved_usage or {},
                    }
                )
            return changed.model_copy(deep=True)

    async def get_step(self, step_id: str) -> StepRecord | None:
        async with self._lock:
            step = self._steps.get(step_id)
            return step.model_copy(deep=True) if step else None

    async def latest_step(self, command_id: str) -> StepRecord | None:
        async with self._lock:
            matches = [step for step in self._steps.values() if step.command_id == command_id]
            if not matches:
                return None
            return max(matches, key=lambda item: item.ordinal).model_copy(deep=True)

    async def list_steps(self, command_id: str) -> tuple[StepRecord, ...]:
        async with self._lock:
            return tuple(
                step.model_copy(deep=True)
                for step in sorted(
                    (item for item in self._steps.values() if item.command_id == command_id),
                    key=lambda item: item.ordinal,
                )
            )

    async def next_eligible(self, *, now_ms: int) -> JournalCommand | None:
        async with self._lock:
            eligible = [
                command
                for command in self._commands.values()
                if command.kind == "execute"
                and command.state is CommandState.QUEUED
                and (command.queue_deadline_ms is None or command.queue_deadline_ms > now_ms)
            ]
            if not eligible:
                return None
            return min(eligible, key=lambda item: item.queue_sequence).model_copy(deep=True)

    async def expire_queued(self, *, now_ms: int) -> tuple[str, ...]:
        async with self._lock:
            expired = [
                command
                for command in self._commands.values()
                if command.kind == "execute"
                and command.state is CommandState.QUEUED
                and command.queue_deadline_ms is not None
                and command.queue_deadline_ms <= now_ms
            ]
        expired_ids: list[str] = []
        for command in expired:
            try:
                await self.transition(
                    command.command_id,
                    expected_version=command.state_version,
                    target=CommandState.FAILED,
                    reason_code="QUEUE_DEADLINE_EXPIRED",
                    actor="worker",
                    occurred_at_ms=now_ms,
                )
                expired_ids.append(command.command_id)
            except StaleCommandVersionError:
                continue
        return tuple(expired_ids)

    async def apply_stop_barrier(
        self, draft: CommandDraft, *, occurred_at_ms: int
    ) -> StopBarrierCommit:
        if draft.kind != "stop":
            raise ValueError("stop barrier requires a stop command")
        async with self._lock:
            key = (draft.caller_scope, draft.request_id)
            existing = self._requests.get(key)
            if existing:
                if existing[0] != draft.request_hash:
                    raise IdempotencyConflictError("IDEMPOTENCY_CONFLICT")
                return StopBarrierCommit(
                    stop_command=self._commands[existing[1]].model_copy(deep=True),
                    idempotency_reused=True,
                    active_command_id=None,
                    cancelled_command_ids=(),
                )

            self._sequence += 1
            stop_command = JournalCommand(
                **draft.model_dump(mode="python"),
                queue_sequence=self._sequence,
                state=CommandState.QUEUED,
                state_version=0,
            )
            self._commands[stop_command.command_id] = stop_command
            self._requests[key] = (draft.request_hash, stop_command.command_id)
            self._facts[stop_command.command_id] = {
                "receipts": [],
                "budgets": [],
                "checkpoints": [],
                "recoveries": [],
            }
            self._append_transition(
                stop_command,
                from_state=None,
                reason_code="STOP_ACCEPTED",
                actor="gateway",
                occurred_at_ms=occurred_at_ms,
            )
            self._accepting_execute = False
            active_command_id: str | None = None
            cancelled: list[str] = []
            for command_id, command in list(self._commands.items()):
                if command.kind != "execute":
                    continue
                if command.state is CommandState.QUEUED:
                    changed = command.model_copy(
                        update={
                            "state": CommandState.CANCELLED_BY_STOP,
                            "state_version": command.state_version + 1,
                            "terminal_at_ms": occurred_at_ms,
                        },
                        deep=True,
                    )
                    self._commands[command_id] = changed
                    self._append_transition(
                        changed,
                        from_state=command.state,
                        reason_code="GLOBAL_STOP",
                        actor="gateway",
                        occurred_at_ms=occurred_at_ms,
                    )
                    cancelled.append(command_id)
                elif command.state in {
                    CommandState.RUNNING,
                    CommandState.RECONCILING,
                    CommandState.BLOCKED_UNKNOWN,
                }:
                    active_command_id = command_id
                    if command.cancel_requested_at_ms is None:
                        self._commands[command_id] = command.model_copy(
                            update={"cancel_requested_at_ms": occurred_at_ms}, deep=True
                        )
            self._projection_version += 1
            return StopBarrierCommit(
                stop_command=stop_command.model_copy(deep=True),
                idempotency_reused=False,
                active_command_id=active_command_id,
                cancelled_command_ids=tuple(cancelled),
            )

    async def recover_startup(self, *, occurred_at_ms: int) -> StartupRecovery:
        async with self._lock:
            snapshots = list(self._commands.values())
        interrupted: list[str] = []
        blocked: list[str] = []
        for command in snapshots:
            if command.state is CommandState.QUEUED:
                await self.transition(
                    command.command_id,
                    expected_version=command.state_version,
                    target=CommandState.INTERRUPTED_BEFORE_START,
                    reason_code="PROCESS_RESTART",
                    actor="startup",
                    occurred_at_ms=occurred_at_ms,
                )
                interrupted.append(command.command_id)
            elif command.state in {CommandState.RUNNING, CommandState.RECONCILING}:
                await self.transition(
                    command.command_id,
                    expected_version=command.state_version,
                    target=CommandState.BLOCKED_UNKNOWN,
                    reason_code="PROCESS_RESTART_UNKNOWN",
                    actor="startup",
                    occurred_at_ms=occurred_at_ms,
                )
                blocked.append(command.command_id)
            elif command.state is CommandState.BLOCKED_UNKNOWN:
                blocked.append(command.command_id)
        if blocked:
            self._accepting_execute = False
        return StartupRecovery(tuple(interrupted), tuple(blocked), bool(blocked))

    async def read_projection(
        self, caller_scope: str, *, limit: int = 20, cursor: str | None = None
    ) -> ProjectionPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = int(cursor) if cursor else 0
        async with self._lock:
            commands = sorted(
                (
                    command
                    for command in self._commands.values()
                    if command.caller_scope == caller_scope and command.queue_sequence > after
                ),
                key=lambda item: item.queue_sequence,
            )
            page = commands[:limit]
            next_cursor = str(page[-1].queue_sequence) if len(commands) > len(page) else None
            return ProjectionPage(
                projection_version=self._projection_version,
                commands=tuple(item.model_copy(deep=True) for item in page),
                next_cursor=next_cursor,
            )
