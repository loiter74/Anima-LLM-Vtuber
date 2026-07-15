"""Typed, revisioned Socket.IO contract for the shared memory runtime."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

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
    ) -> None:
        self._base = base
        self._global_config = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._job_tasks: dict[str, asyncio.Task[None]] = {}
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
        return await self._mutate(
            sid,
            str(data.get("id") or ""),
            "change_memory",
            summary=summary,
        )

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
        del data
        try:
            memory = await self._get_memory(sid)
        except Exception as exc:
            return _error("UNAVAILABLE", str(exc))
        job_id = uuid.uuid4().hex
        self._jobs[job_id] = {"job_id": job_id, "status": "accepted", "progress": 0}
        task = asyncio.create_task(
            self._run_organize_job(sid, job_id, memory),
            name=f"memory-organize-{job_id[:8]}",
        )
        self._job_tasks[job_id] = task
        return _ok(dict(self._jobs[job_id]))

    async def _run_organize_job(self, sid: str, job_id: str, memory: Any) -> None:
        try:
            self._jobs[job_id].update(status="running", progress=30)
            await self.sio.emit(
                EVENTS["memory"]["organize_progress"]["name"],
                {**self._jobs[job_id], "text": "Running metabolism tick..."},
                to=sid,
            )
            await memory.run_metabolism_tick()
            revision = await memory.store.get_revision()
            self._jobs[job_id].update(status="completed", progress=100, revision=revision)
            await self.sio.emit(
                EVENTS["memory"]["organize_result"]["name"],
                {
                    **self._jobs[job_id],
                    "message": "Memory organized",
                },
                to=sid,
            )
        except Exception as exc:
            self._jobs[job_id].update(status="failed", error=str(exc))
            await self.sio.emit(
                EVENTS["memory"]["organize_result"]["name"],
                {**self._jobs[job_id], "message": str(exc)},
                to=sid,
            )

    async def wait_for_job(self, job_id: str) -> None:
        task = self._job_tasks.get(job_id)
        if task is not None:
            await task

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
