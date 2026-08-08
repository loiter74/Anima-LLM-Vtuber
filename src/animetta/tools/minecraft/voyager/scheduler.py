"""Repository-backed strict FIFO scheduler with exactly one consumer."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from .command_models import CommandState
from .journal import CommandJournal, JournalCommand, StaleCommandVersionError


class CommandExecutionError(RuntimeError):
    """Controller-selected terminal outcome for the single consumer to commit."""

    def __init__(
        self,
        *,
        terminal_state: CommandState,
        reason_code: str,
        message: str,
        details: dict | None = None,
        requires_reconciliation: bool = False,
        terminal_result: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.terminal_state = terminal_state
        self.reason_code = reason_code
        self.details = details or {}
        self.requires_reconciliation = requires_reconciliation
        self.terminal_result = terminal_result


class VoyagerCommandScheduler:
    def __init__(
        self,
        *,
        repository: CommandJournal,
        consumer: Callable[[JournalCommand], Awaitable[None]],
        now_ms: Callable[[], int],
        poll_interval: float = 0.05,
        on_command_changed: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._repository = repository
        self._consumer = consumer
        self._now_ms = now_ms
        self._poll_interval = poll_interval
        self._on_command_changed = on_command_changed
        self._consumer_lock = asyncio.Lock()
        self._worker: asyncio.Task[None] | None = None
        self._closing = False

    async def _notify(self, command_id: str) -> None:
        if self._on_command_changed is None:
            return
        with contextlib.suppress(Exception):
            await self._on_command_changed(command_id)

    async def expire_queued(self) -> tuple[str, ...]:
        method = getattr(self._repository, "expire_queued")
        return await method(now_ms=self._now_ms())

    async def run_once(self) -> bool:
        async with self._consumer_lock:
            await self.expire_queued()
            command = await self._repository.next_eligible(now_ms=self._now_ms())  # type: ignore[attr-defined]
            if command is None:
                return False
            try:
                running = await self._repository.transition(
                    command.command_id,
                    expected_version=command.state_version,
                    target=CommandState.RUNNING,
                    reason_code="DISPATCHED",
                    actor="worker",
                    occurred_at_ms=self._now_ms(),
                )
            except StaleCommandVersionError:
                return False
            await self._notify(running.command_id)
            try:
                await self._consumer(running)
            except CommandExecutionError as exc:
                current = running
                if exc.requires_reconciliation:
                    current = await self._repository.transition(
                        current.command_id,
                        expected_version=current.state_version,
                        target=CommandState.RECONCILING,
                        reason_code="RECONCILIATION_REQUIRED",
                        actor="controller",
                        occurred_at_ms=self._now_ms(),
                        details=exc.details,
                    )
                await self._repository.transition(
                    current.command_id,
                    expected_version=current.state_version,
                    target=exc.terminal_state,
                    reason_code=exc.reason_code,
                    actor="controller",
                    occurred_at_ms=self._now_ms(),
                    details={"message": str(exc), **exc.details},
                    terminal_result=exc.terminal_result,
                )
                await self._notify(running.command_id)
                return True
            except Exception as exc:
                await self._repository.transition(
                    running.command_id,
                    expected_version=running.state_version,
                    target=CommandState.FAILED,
                    reason_code=type(exc).__name__.upper(),
                    actor="controller",
                    occurred_at_ms=self._now_ms(),
                    details={"message": str(exc)},
                )
                await self._notify(running.command_id)
                return True
            await self._repository.transition(
                running.command_id,
                expected_version=running.state_version,
                target=CommandState.SUCCEEDED,
                reason_code="VERIFIED",
                actor="controller",
                occurred_at_ms=self._now_ms(),
            )
            await self._notify(running.command_id)
            return True

    async def _run(self) -> None:
        while not self._closing:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self._poll_interval)

    def start(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._closing = False
        self._worker = asyncio.create_task(self._run(), name="voyager-command-worker")

    async def stop(self) -> None:
        self._closing = True
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
