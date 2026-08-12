"""Typed, revisioned Socket.IO contract for the shared memory runtime."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from ....services.command_inbox import CommandDecision, CommandInbox, CommandKey
from ...socket_events import EVENTS
from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..session import SessionManager


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


class MemoryHandlers(BaseSocketHandler):
    """Memory queries/mutations with deterministic acknowledgements."""

    def __init__(
        self,
        sio: AsyncServer,
        session_manager: SessionManager,
        base: BaseSocketHandler,
        command_inbox: CommandInbox | None = None,
    ) -> None:
        self._base = base
        self._global_config = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._job_tasks: dict[str, asyncio.Task[None]] = {}
        self._command_inbox = command_inbox or CommandInbox(":memory:")
        self._active_organize_id: str | None = None
        self._organize_subscribers: dict[str, set[str]] = {}
        super().__init__(sio, session_manager, base.desktop_manager, base.live2d_manager)

    @property
    def global_config(self) -> Any:
        if self._base and self._base.global_config:
            return self._base.global_config
        return self._global_config

    @global_config.setter
    def global_config(self, value: Any) -> None:
        self._global_config = value
        if self._base:
            self._base.global_config = value

    async def _get_context(self, sid: str) -> Any:
        return await self._base.get_or_create_context(sid)

    async def _get_memory(self, sid: str) -> Any:
        context = await self._get_context(sid)
        memory = getattr(context, "memory_system", None)
        if memory is None:
            raise RuntimeError("Memory system not available")
        return memory

    async def on_list(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            memory = await self._get_memory(sid)
            result = await memory.list_memories(
                limit=int(data.get("limit") or 50),
                cursor=data.get("cursor"),
                scope=data.get("scope"),
            )
            return _ok(result)
        except (TypeError, ValueError) as exc:
            return _error("INVALID_REQUEST", str(exc))
        except Exception as exc:
            logger.warning("[MemoryHandlers] list failed: {}", exc)
            return _error("UNAVAILABLE", str(exc))

    async def on_get(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        atom_id = str(data.get("id") or "").strip()
        if not atom_id:
            return _error("INVALID_REQUEST", "id is required")
        try:
            memory = await self._get_memory(sid)
            item = await memory.get_memory(atom_id)
            if item is None:
                return _error("NOT_FOUND", "memory not found")
            return _ok({"item": item, "revision": await memory.store.get_revision()})
        except Exception as exc:
            return _error("UNAVAILABLE", str(exc))

    async def on_search(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        query = str(data.get("query") or "").strip()
        if not query:
            return _error("INVALID_REQUEST", "query is required")
        try:
            memory = await self._get_memory(sid)
            return _ok(
                await memory.search_memories(
                    query,
                    limit=int(data.get("limit") or 50),
                )
            )
        except (TypeError, ValueError) as exc:
            return _error("INVALID_REQUEST", str(exc))
        except Exception as exc:
            return _error("UNAVAILABLE", str(exc))

    async def on_pin(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._mutate(
            sid,
            str(data.get("id") or ""),
            "pin_memory",
            pinned=bool(data.get("pinned", True)),
        )

    async def on_forget(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self._mutate(sid, str(data.get("id") or ""), "forget_memory")

    async def on_change(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        summary = str(data.get("summary") or "").strip()
        if not summary:
            return _error("INVALID_REQUEST", "summary is required")
        atom_id = str(data.get("id") or "")
        task_id = str(data.get("task_id") or uuid.uuid4())
        expected_version = data.get("expected_version")
        if not atom_id:
            return _error("INVALID_REQUEST", "id is required")
        key = CommandKey("dashboard", "memory.change", task_id)
        accepted = await self._command_inbox.accept(
            key,
            {"id": atom_id, "summary": summary, "expected_version": expected_version},
        )
        if accepted.decision is CommandDecision.CONFLICT:
            return _error("IDEMPOTENCY_CONFLICT", "task_id was already used")
        if accepted.decision is CommandDecision.REPLAY and accepted.task:
            return accepted.task.result or _error("UNAVAILABLE", "missing task result")
        if accepted.decision is CommandDecision.TERMINAL and accepted.task:
            return _error(
                accepted.task.error_code or accepted.task.status.value,
                accepted.task.error_message or "memory change did not complete",
            )
        if accepted.decision is CommandDecision.OBSERVE:
            return _error("RESOURCE_BUSY", "memory change is already running")
        await self._command_inbox.mark_processing(key)
        try:
            memory = await self._get_memory(sid)
            current = await memory.get_memory(atom_id)
            if current is None:
                result = _error("NOT_FOUND", "memory not found")
                await self._command_inbox.fail(
                    key, error_code="NOT_FOUND", error_message="memory not found"
                )
                return result
            if expected_version is None:
                expected_version = current.get("version")
            if not isinstance(expected_version, int) or isinstance(expected_version, bool):
                await self._command_inbox.fail(
                    key,
                    error_code="INVALID_REQUEST",
                    error_message="expected_version must be an integer",
                )
                return _error("INVALID_REQUEST", "expected_version must be an integer")
            if current.get("version") != expected_version:
                await self._command_inbox.fail(
                    key,
                    error_code="STALE_MEMORY_VERSION",
                    error_message="memory version has changed",
                )
                return _error("STALE_MEMORY_VERSION", "memory version has changed")
            item = await memory.change_memory(atom_id, summary=summary)
            result = _ok({"item": item, "revision": await memory.store.get_revision()})
            await self._command_inbox.succeed(key, result)
            return result
        except Exception as exc:
            await self._command_inbox.fail(key, error_code="UNAVAILABLE", error_message=str(exc))
            return _error("UNAVAILABLE", str(exc))

    async def _mutate(
        self,
        sid: str,
        atom_id: str,
        method_name: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not atom_id:
            return _error("INVALID_REQUEST", "id is required")
        try:
            memory = await self._get_memory(sid)
            item = await getattr(memory, method_name)(atom_id, **kwargs)
            if item is None:
                return _error("NOT_FOUND", "memory not found")
            return _ok({"item": item, "revision": await memory.store.get_revision()})
        except ValueError as exc:
            return _error("INVALID_REQUEST", str(exc))
        except Exception as exc:
            return _error("UNAVAILABLE", str(exc))

    async def on_memory_organize(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            memory = await self._get_memory(sid)
        except Exception as exc:
            return _error("UNAVAILABLE", str(exc))
        job_id = str(data.get("task_id") or uuid.uuid4())
        key = CommandKey("dashboard", "memory.organize", job_id)
        accepted = await self._command_inbox.accept(key, {"operation": "organize"})
        if accepted.decision is CommandDecision.CONFLICT:
            return _error("IDEMPOTENCY_CONFLICT", "task_id was already used")
        if accepted.decision is CommandDecision.REPLAY and accepted.task:
            return _ok(accepted.task.result or accepted.task.snapshot(reused=True))
        if accepted.decision is CommandDecision.TERMINAL and accepted.task:
            return _error(
                accepted.task.error_code or accepted.task.status.value,
                accepted.task.error_message or "memory organization did not complete",
            )
        if accepted.decision is CommandDecision.OBSERVE:
            self._organize_subscribers.setdefault(job_id, set()).add(sid)
            return _ok(dict(self._jobs.get(job_id) or accepted.task.snapshot(reused=True)))
        if self._active_organize_id is not None:
            await self._command_inbox.fail(
                key, error_code="RESOURCE_BUSY", error_message="Memory organization is active"
            )
            return _error("RESOURCE_BUSY", "Memory organization is active")
        self._active_organize_id = job_id
        self._organize_subscribers.setdefault(job_id, set()).add(sid)
        await self._command_inbox.mark_processing(key)
        self._jobs[job_id] = {"job_id": job_id, "status": "accepted", "progress": 0}
        task = asyncio.create_task(
            self._run_organize_job(sid, job_id, memory),
            name=f"memory-organize-{job_id[:8]}",
        )
        self._job_tasks[job_id] = task
        return _ok(dict(self._jobs[job_id]))

    async def _run_organize_job(self, sid: str, job_id: str, memory: Any) -> None:
        key = CommandKey("dashboard", "memory.organize", job_id)
        try:
            self._jobs[job_id].update(status="running", progress=30)
            progress = {**self._jobs[job_id], "text": "Running metabolism tick..."}
            await self._command_inbox.update_progress(key, progress)
            for subscriber in tuple(self._organize_subscribers.get(job_id, ())):
                await self.sio.emit(
                    EVENTS["memory"]["organize_progress"]["name"], progress, to=subscriber
                )
            await memory.run_metabolism_tick()
            revision = await memory.store.get_revision()
            self._jobs[job_id].update(status="completed", progress=100, revision=revision)
            result = {**self._jobs[job_id], "message": "Memory organized"}
            await self._command_inbox.succeed(key, result)
            for subscriber in tuple(self._organize_subscribers.get(job_id, ())):
                await self.sio.emit(
                    EVENTS["memory"]["organize_result"]["name"],
                    result,
                    to=subscriber,
                )
        except Exception as exc:
            self._jobs[job_id].update(status="failed", error=str(exc))
            await self._command_inbox.fail(
                key, error_code="ORGANIZE_FAILED", error_message=str(exc)
            )
            for subscriber in tuple(self._organize_subscribers.get(job_id, ())):
                await self.sio.emit(
                    EVENTS["memory"]["organize_result"]["name"],
                    {**self._jobs[job_id], "message": str(exc)},
                    to=subscriber,
                )
        finally:
            if self._active_organize_id == job_id:
                self._active_organize_id = None
            self._organize_subscribers.pop(job_id, None)
            self._job_tasks.pop(job_id, None)

    async def wait_for_job(self, job_id: str) -> None:
        task = self._job_tasks.get(job_id)
        if task is not None:
            await task

    def observe_organize(self, sid: str, job_id: str) -> None:
        self._organize_subscribers.setdefault(job_id, set()).add(sid)

    async def on_job(self, sid: str, data: dict[str, Any]) -> dict[str, Any]:
        del sid
        job_id = str(data.get("job_id") or "")
        job = self._jobs.get(job_id)
        return _ok(dict(job)) if job else _error("NOT_FOUND", "job not found")

    async def on_get_wiki_pages(
        self,
        sid: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Compatibility alias for the legacy MemoryPanel contract."""
        try:
            memory = await self._get_memory(sid)
            pages = await memory.list_wiki_pages(limit=int(data.get("limit") or 50))
            return {"pages": pages, "revision": await memory.store.get_revision()}
        except Exception as exc:
            return {"pages": [], "error": str(exc)}
