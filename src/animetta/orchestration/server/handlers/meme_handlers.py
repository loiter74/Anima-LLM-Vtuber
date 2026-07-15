"""Meme review Socket.IO handlers."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from loguru import logger

from ....services.bilibili import MemeCollector
from ....services.meme.analyzer import Meme, MemeCognitiveAnalyzer, MemePool
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

    def set_review(self, meme_id: str, status: str) -> None:
        self._review_status[meme_id] = status

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
    ) -> None:
        self._base = base
        self._store = _InMemoryMemeStore()
        self._pool = MemePool(self._store)
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
        )
        source = str(data.get("source") or "user")
        if meme:
            meme.source_platform = source
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
        try:
            collector = MemeCollector(llm_client=await self._get_llm(sid))
            candidates = await collector.collect()
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
                )
                if meme:
                    meme.source_platform = "bilibili"
                    self._store.update(meme)
            payload = {"ok": True, "count": len(candidates)}
        except Exception as e:
            logger.exception("[MemeHandlers] collection failed")
            payload = {"ok": False, "error": str(e)}

        await self.sio.emit(EVENTS["meme"]["collect"]["name"], payload, to=sid)
        return payload
