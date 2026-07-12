"""Single-owner control plane for Voyager learning, live, and fallback sessions."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

from animetta.tools.gamebot.contracts import ActionReceipt
from animetta.tools.gamebot.runtime import GameBotRuntime

from .contracts import (
    VoyagerMode,
    VoyagerSessionContext,
    VoyagerSessionState,
    VoyagerStatus,
)
from .policy import VoyagerPolicy
from .recovery import RecoveryCoordinator, RecoveryState
from .repository import VoyagerRepository


class VoyagerSession(Protocol):
    async def run(self) -> None: ...


SessionFactory = Callable[[VoyagerSessionContext], VoyagerSession]


class VoyagerController:
    """Serialize mode transitions and own exactly one active session task."""

    def __init__(
        self,
        *,
        runtime: GameBotRuntime,
        policy: VoyagerPolicy,
        session_factories: dict[VoyagerMode, SessionFactory],
        repository: VoyagerRepository,
        recovery: RecoveryCoordinator | None = None,
    ) -> None:
        self._runtime = runtime
        self._policy = policy
        self._session_factories = dict(session_factories)
        self._repository = repository
        self._recovery = recovery
        self._transition_lock = asyncio.Lock()
        self._session: VoyagerSession | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._status = VoyagerStatus()

    async def start_learning(self, goal: str | None = None) -> VoyagerStatus:
        return await self._transition(VoyagerMode.LEARN, goal or "")

    async def start_live(self) -> VoyagerStatus:
        return await self._transition(VoyagerMode.LIVE, "")

    async def start_fallback(self) -> VoyagerStatus:
        return await self._transition(VoyagerMode.FALLBACK, "")

    async def _transition(self, mode: VoyagerMode, goal: str) -> VoyagerStatus:
        async with self._transition_lock:
            if (
                self._status.mode is mode
                and self._status.current_task == goal
                and self._session_task is not None
                and not self._session_task.done()
            ):
                return self._status.model_copy(deep=True)

            return await self._start_session_locked(mode, goal, stop_existing=True)

    async def _start_session_locked(
        self,
        mode: VoyagerMode,
        goal: str,
        *,
        stop_existing: bool,
    ) -> VoyagerStatus:
        manifest = await self._runtime.get_capabilities()
        policy_report = self._policy.validate_manifest(manifest)
        if not policy_report.allowed:
            codes = ",".join(violation.code for violation in policy_report.violations)
            raise RuntimeError(f"Voyager runtime policy rejected: {codes}")

        factory = self._session_factories.get(mode)
        if factory is None:
            raise RuntimeError(f"No Voyager session factory configured for {mode.value}")

        if stop_existing:
            await self._stop_active_locked()
        session_id = f"voyager-{uuid4().hex}"
        context = VoyagerSessionContext(
            session_id=session_id,
            mode=mode,
            runtime=self._runtime,
            manifest=manifest,
            authorized_capabilities=frozenset(policy_report.authorized_capabilities),
            repository=self._repository,
            goal=goal,
        )
        session = factory(context)
        self._session = session
        self._status = VoyagerStatus(
            mode=mode,
            state=VoyagerSessionState.RUNNING,
            session_id=session_id,
            runtime_id=manifest.runtime_id,
            current_task=goal,
        )
        await self._repository.save_status(self._status)
        self._session_task = asyncio.create_task(
            session.run(), name=f"voyager-{mode.value}-{session_id}"
        )
        await asyncio.sleep(0)
        return self._status.model_copy(deep=True)

    async def recover(
        self,
        *,
        interrupted_task_id: str,
        active_correlation_id: str,
        partial_receipts: list[ActionReceipt],
    ) -> VoyagerStatus:
        async with self._transition_lock:
            if self._recovery is None:
                raise RuntimeError("Voyager recovery coordinator is not configured")
            previous = self._status
            if previous.mode in {VoyagerMode.STOPPED, VoyagerMode.RECOVERING}:
                raise RuntimeError("Voyager recovery requires an active session")

            await self._stop_active_locked()
            self._status = VoyagerStatus(
                mode=VoyagerMode.RECOVERING,
                state=VoyagerSessionState.STARTING,
                session_id=previous.session_id,
                runtime_id=previous.runtime_id,
                current_task=previous.current_task,
            )
            await self._repository.save_status(self._status)
            result = await self._recovery.recover(
                session_id=previous.session_id,
                interrupted_task_id=interrupted_task_id,
                active_correlation_id=active_correlation_id,
                partial_receipts=partial_receipts,
            )
            if result.state is RecoveryState.RESUMED:
                return await self._start_session_locked(
                    previous.mode,
                    previous.current_task,
                    stop_existing=False,
                )

            self._status = VoyagerStatus(
                mode=VoyagerMode.RECOVERING,
                state=VoyagerSessionState.QUARANTINED,
                session_id=previous.session_id,
                runtime_id=previous.runtime_id,
                current_task=previous.current_task,
                last_failure=result.reason,
            )
            await self._repository.save_status(self._status)
            return self._status.model_copy(deep=True)

    async def run_live_goal(self, goal: str) -> dict[str, Any]:
        async with self._transition_lock:
            if self._status.mode is not VoyagerMode.LIVE or self._session is None:
                raise RuntimeError("Voyager live goal requires live mode")
            run_goal = getattr(self._session, "run_goal", None)
            if not callable(run_goal):
                raise RuntimeError("Active Voyager live session cannot run goals")
            return await run_goal(goal)

    async def stop(self) -> VoyagerStatus:
        async with self._transition_lock:
            if self._status.mode is VoyagerMode.STOPPED and self._session_task is None:
                return self._status.model_copy(deep=True)
            await self._stop_active_locked()
            self._status = VoyagerStatus()
            await self._repository.save_status(self._status)
            return self._status.model_copy(deep=True)

    async def _stop_active_locked(self) -> None:
        task = self._session_task
        self._session_task = None
        self._session = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def status(self) -> VoyagerStatus:
        async with self._transition_lock:
            return self._status.model_copy(deep=True)
