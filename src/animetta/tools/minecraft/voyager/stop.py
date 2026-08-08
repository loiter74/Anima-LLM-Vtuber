"""Durable global stop barrier and post-commit cancellation acceleration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import uuid4

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

from .command_models import TERMINAL_COMMAND_STATES, CommandState
from .journal import CommandDraft, CommandJournal


@dataclass(frozen=True)
class StopResult:
    stop_command_id: str
    idempotency_reused: bool
    active_command_id: str | None
    cancelled_command_ids: tuple[str, ...]
    recovery_error: str | None = None


class GlobalStopBarrier:
    def __init__(
        self,
        *,
        repository: CommandJournal,
        signal_active: Callable[[str], Awaitable[str | None]],
        now_ms: Callable[[], int],
        completion_timeout: float = 0.1,
    ) -> None:
        self._repository = repository
        self._signal_active = signal_active
        self._now_ms = now_ms
        self._completion_timeout = completion_timeout

    async def _wait_for_active_terminal(self, command_id: str) -> str | None:
        deadline = asyncio.get_running_loop().time() + self._completion_timeout
        while True:
            command = await self._repository.get_command(command_id)
            if command is None:
                return "RECOVERY_INCOMPLETE"
            if command.state in TERMINAL_COMMAND_STATES:
                return (
                    "RECOVERY_INCOMPLETE" if command.state is CommandState.BLOCKED_UNKNOWN else None
                )
            if asyncio.get_running_loop().time() >= deadline:
                return "RECOVERY_INCOMPLETE"
            await asyncio.sleep(0.05)

    async def _commit_stop_outcome(self, command_id: str, *, recovery_error: str | None) -> None:
        command = await self._repository.get_command(command_id)
        if command is None or command.state is not CommandState.QUEUED:
            return
        running = await self._repository.transition(
            command_id,
            expected_version=command.state_version,
            target=CommandState.RUNNING,
            reason_code="STOP_BARRIER_COMMITTED",
            actor="controller",
            occurred_at_ms=self._now_ms(),
        )
        await self._repository.transition(
            command_id,
            expected_version=running.state_version,
            target=(CommandState.FAILED if recovery_error is not None else CommandState.SUCCEEDED),
            reason_code=recovery_error or "STOP_COMPLETED",
            actor="controller",
            occurred_at_ms=self._now_ms(),
        )

    async def stop(self, *, caller_scope: str, request_id: str, reason: str) -> StopResult:
        now = self._now_ms()
        request_hash = canonical_json_hash(
            {"contract_version": "1", "kind": "stop", "reason": reason}
        )
        draft = CommandDraft(
            command_id=f"stop-{uuid4().hex}",
            caller_scope=caller_scope,
            request_id=request_id,
            request_hash=request_hash,
            kind="stop",
            payload={"reason": reason},
            requested_budget={},
            effective_budget={},
            accepted_at_ms=now,
        )
        commit = await self._repository.apply_stop_barrier(draft, occurred_at_ms=now)
        if commit.idempotency_reused:
            return StopResult(
                stop_command_id=commit.stop_command.command_id,
                idempotency_reused=True,
                active_command_id=None,
                cancelled_command_ids=(),
                recovery_error=(
                    "RECOVERY_INCOMPLETE"
                    if commit.stop_command.state is CommandState.FAILED
                    else None
                ),
            )
        recovery_error = None
        if commit.active_command_id:
            recovery_error = await self._signal_active(commit.active_command_id)
            if recovery_error is None:
                recovery_error = await self._wait_for_active_terminal(commit.active_command_id)
        await self._commit_stop_outcome(
            commit.stop_command.command_id, recovery_error=recovery_error
        )
        return StopResult(
            stop_command_id=commit.stop_command.command_id,
            idempotency_reused=False,
            active_command_id=commit.active_command_id,
            cancelled_command_ids=commit.cancelled_command_ids,
            recovery_error=recovery_error,
        )
