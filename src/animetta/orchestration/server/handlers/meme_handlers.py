"""Meme review Socket.IO handlers."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from loguru import logger

from ....services.bilibili import MemeCollector
from ....services.command_inbox import (
    CommandDecision,
    CommandInbox,
    CommandKey,
    CommandStatus,
)
from ....services.meme.analyzer import (
    Meme,
    MemeCognitiveAnalyzer,
    MemePool,
    stable_meme_id,
)
from ...socket_events import EVENTS
from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..session import SessionManager


class _InMemoryMemeStore:
    """Small runtime store backing the frontend review workflow."""

    def __init__(self) -> None:
        self._items: dict[str, Meme] = {}
        self._review_status: dict[str, str] = {}

    def update(self, meme: Meme) -> None:
        self._items[meme.id] = meme

    def get(self, meme_id: str) -> Meme | None:
        return self._items.get(meme_id)

    def set_review(self, meme_id: str, status: str) -> bool:
        if self._review_status.get(meme_id) == status:
            return False
        self._review_status[meme_id] = status
        return True

    def list_pending(self, source_platform: str = "", limit: int = 50) -> list[Meme]:
        memes = [
            meme
            for meme in self._items.values()
            if meme.id not in self._review_status
            and (not source_platform or meme.source_platform == source_platform)
        ]
        return sorted(memes, key=lambda item: item.created_at, reverse=True)[:limit]

    def dataset(self) -> list[dict[str, Any]]:
        return [
            {**_meme_to_payload(meme), "review_status": status}
            for meme_id, status in self._review_status.items()
            if (meme := self._items.get(meme_id)) is not None
        ]


def _analysis_to_payload(analysis: Any) -> dict[str, Any] | None:
    if analysis is None:
        return None
    if isinstance(analysis, dict):
        return dict(analysis)
    return asdict(analysis)


def _meme_to_payload(meme: Meme) -> dict[str, Any]:
    return {
        "id": meme.id,
        "text": meme.text,
        "context_hint": meme.context_hint,
        "tags": meme.tags,
        "source_platform": meme.source_platform,
        "base_score": meme.confidence,
        "cognitive_analysis": _analysis_to_payload(meme.cognitive_analysis),
        "format_id": meme.format_id,
        "format_slots": meme.format_slots,
        "format_confidence": meme.format_confidence,
        "rendered_text": meme.rendered_text,
        "mode": meme.mode,
    }


class MemeHandlers(BaseSocketHandler):
    """Handlers for the meme review frontend events."""

    def __init__(
        self,
        sio: AsyncServer,
        session_manager: SessionManager,
        base: BaseSocketHandler,
        command_inbox: CommandInbox | None = None,
    ) -> None:
        self._base = base
        self._store = _InMemoryMemeStore()
        self._pool = MemePool(self._store)
        self._command_inbox = command_inbox or CommandInbox(":memory:")
        self._active_collection_id: str | None = None
        self._collect_subscribers: dict[str, set[str]] = {}
        super().__init__(sio, session_manager, base.desktop_manager, base.live2d_manager)

    async def _get_llm(self, sid: str) -> Any | None:
        try:
            ctx = await self._base.get_or_create_context(sid)
            return getattr(ctx, "llm_engine", None)
        except Exception as e:
            logger.debug("[MemeHandlers] LLM context unavailable: {}", e)
            return None

    async def on_add_meme(self, sid: str, data: dict) -> dict[str, Any]:
        """Add a user-provided meme candidate to the runtime pool."""
        text = str(data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text is required"}

        source = str(data.get("source") or "user")
        analyzer = MemeCognitiveAnalyzer(
            llm_client=await self._get_llm(sid),
            meme_pool=self._pool,
        )
        meme = await analyzer.analyze_and_ingest(
            text=text,
            context_hint=str(data.get("context_hint") or ""),
            tags=list(data.get("tags") or []),
            source_url=str(data.get("source_url") or ""),
            format_id=str(data.get("format_id") or ""),
            format_slots=dict(data.get("format_slots") or {}),
            format_confidence=data.get("format_confidence"),
            rendered_text=str(data.get("rendered_text") or ""),
            mode=str(data.get("mode") or ""),
            source_platform=source,
        )
        if meme:
            self._store.update(meme)
        if meme is None:
            meme = self._pool.add_from_candidate(
                text=text,
                context_hint=str(data.get("context_hint") or ""),
                confidence=0.4,
                tags=list(data.get("tags") or []),
                format_id=str(data.get("format_id") or ""),
                format_slots=dict(data.get("format_slots") or {}),
                format_confidence=data.get("format_confidence"),
                rendered_text=str(data.get("rendered_text") or ""),
                mode=str(data.get("mode") or ""),
                source_platform=source,
            )
            if meme:
                meme.source_platform = source
                self._store.update(meme)

        return {"ok": meme is not None, "meme": _meme_to_payload(meme) if meme else None}

    async def on_list_memes(self, sid: str, data: dict) -> dict[str, Any]:
        source_platform = str(data.get("source_platform") or "")
        limit = int(data.get("limit") or 50)
        payload = {
            "memes": [
                _meme_to_payload(meme) for meme in self._store.list_pending(source_platform, limit)
            ]
        }
        await self.sio.emit(EVENTS["meme"]["list"]["name"], payload, to=sid)
        return payload

    async def on_review_meme(self, sid: str, data: dict) -> dict[str, Any]:
        meme_id = str(data.get("meme_id") or "")
        status = str(data.get("status") or "")
        if status not in {"good", "bad"}:
            payload = {"ok": False, "error": "status must be good or bad"}
        elif self._store.get(meme_id) is None:
            payload = {"ok": False, "error": "meme not found"}
        else:
            self._store.set_review(meme_id, status)
            payload = {
                "ok": True,
                "feedback": "已收录为好梗" if status == "good" else "已标记为不适合",
            }

        await self.sio.emit(EVENTS["meme"]["review"]["name"], payload, to=sid)
        return payload

    async def on_export_dataset(self, sid: str, data: dict) -> dict[str, Any]:
        payload = {"memes": self._store.dataset()}
        await self.sio.emit(EVENTS["meme"]["dataset"]["name"], payload, to=sid)
        return payload

    async def on_collect_memes(self, sid: str, data: dict) -> dict[str, Any]:
        task_id = str(data.get("task_id") or uuid.uuid4())
        key = CommandKey("dashboard", "meme.collect", task_id)
        accepted = await self._command_inbox.accept(
            key,
            {"source": str(data.get("source") or "bilibili")},
        )
        if accepted.decision is CommandDecision.CONFLICT:
            return {"ok": False, "task_id": task_id, "error": "IDEMPOTENCY_CONFLICT"}
        if accepted.decision is CommandDecision.REPLAY and accepted.task:
            payload = dict(accepted.task.result or {})
            self._restore_candidates(payload.get("candidates"))
            await self.sio.emit(EVENTS["meme"]["collect"]["name"], payload, to=sid)
            return payload
        if accepted.decision is CommandDecision.TERMINAL and accepted.task:
            return {
                "ok": False,
                "task_id": task_id,
                "error": accepted.task.error_code or accepted.task.status.value,
            }
        self._collect_subscribers.setdefault(task_id, set()).add(sid)
        if accepted.decision is CommandDecision.OBSERVE:
            return {"ok": True, "task_id": task_id, "status": "processing", "reused": True}

        if self._active_collection_id is not None:
            await self._command_inbox.fail(
                key, error_code="RESOURCE_BUSY", error_message="Meme collection is already running"
            )
            return {"ok": False, "task_id": task_id, "error": "RESOURCE_BUSY"}
        self._active_collection_id = task_id
        await self._command_inbox.mark_processing(key)
        try:
            collector = MemeCollector(llm_client=await self._get_llm(sid))
            candidates = await collector.collect()
            collected: list[dict[str, Any]] = []
            for candidate in candidates:
                meme = self._pool.add_from_candidate(
                    text=candidate.text,
                    context_hint=candidate.context_hint,
                    confidence=min(max(candidate.frequency / 10, 0.1), 1.0),
                    tags=candidate.tags,
                    format_id=candidate.format_id,
                    format_slots=candidate.format_slots,
                    format_confidence=candidate.format_confidence,
                    rendered_text=candidate.rendered_text,
                    mode=candidate.mode,
                    source_platform="bilibili",
                )
                if meme:
                    self._store.update(meme)
                    collected.append(_meme_to_payload(meme))
            payload = {
                "ok": True,
                "task_id": task_id,
                "status": "succeeded",
                "count": len(candidates),
                "candidates": collected,
            }
            await self._command_inbox.succeed(key, payload)
        except Exception as e:
            logger.exception("[MemeHandlers] collection failed")
            await self._command_inbox.fail(
                key, error_code="COLLECTION_FAILED", error_message=str(e)
            )
            payload = {"ok": False, "task_id": task_id, "error": str(e)}
        finally:
            if self._active_collection_id == task_id:
                self._active_collection_id = None

        for subscriber in tuple(self._collect_subscribers.pop(task_id, ())):
            await self.sio.emit(EVENTS["meme"]["collect"]["name"], payload, to=subscriber)
        return payload

    async def restore_latest_collection(self) -> None:
        latest = await self._command_inbox.latest(
            scope="dashboard",
            kind="meme.collect",
            status=CommandStatus.SUCCEEDED,
        )
        if latest and latest.result:
            self._restore_candidates(latest.result.get("candidates"))

    def observe_collection(self, sid: str, task_id: str) -> None:
        self._collect_subscribers.setdefault(task_id, set()).add(sid)

    def _restore_candidates(self, raw: object) -> None:
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            meme = Meme(
                id=str(item.get("id") or stable_meme_id(str(item["text"]), "bilibili")),
                text=str(item["text"]),
                context_hint=str(item.get("context_hint") or ""),
                confidence=float(item.get("base_score") or 0),
                tags=[str(tag) for tag in item.get("tags", [])],
                source_platform=str(item.get("source_platform") or "bilibili"),
                cognitive_analysis=item.get("cognitive_analysis"),
                format_id=str(item.get("format_id") or ""),
                format_slots=dict(item.get("format_slots") or {}),
                format_confidence=item.get("format_confidence"),
                rendered_text=str(item.get("rendered_text") or ""),
                mode=str(item.get("mode") or ""),
                created_at=time.time(),
            )
            self._store.update(meme)
