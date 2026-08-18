"""Application-scoped, process-local conversation continuity state."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from animetta.services.bilibili.response_policy import PROACTIVE_TOPIC_SOURCE

Mood = Literal["neutral", "bright", "tired", "irritated"]
ScopeKind = Literal["livestream", "conversation"]
PROACTIVE_TOPIC_HISTORY_LABEL = "[直播主持人自主发言触发，不是观众弹幕]"


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One completed, publicly delivered user/assistant pair."""

    user_text: str
    final_response: str
    task_id: str
    actor_role: str | None = None
    source: str | None = None

    @property
    def prompt_user_text(self) -> str:
        if self.actor_role == "host" and self.source == PROACTIVE_TOPIC_SOURCE:
            return PROACTIVE_TOPIC_HISTORY_LABEL
        if self.actor_role == "developer" or self.source == "developer_console":
            return (
                "[开发者后台私有上下文：可使用回答所需的普通事实；"
                f"不得复述整段原文或暴露幕后信息] {self.user_text}"
            )
        return self.user_text


@dataclass(frozen=True, slots=True)
class ConversationScope:
    kind: ScopeKind
    scope_id: str


def resolve_conversation_scope(
    *,
    conversation_id: str | None,
    session_id: str,
    metadata: Mapping[str, Any],
) -> ConversationScope:
    """Resolve the authoritative server-side continuity scope for one turn."""

    live_session_id = metadata.get("live_session_id")
    if (
        metadata.get("audience") == "livestream"
        and isinstance(live_session_id, str)
        and live_session_id.strip()
    ):
        return ConversationScope("livestream", live_session_id.strip())
    stable_id = conversation_id.strip() if isinstance(conversation_id, str) else ""
    return ConversationScope("conversation", stable_id or session_id)


@dataclass(slots=True)
class ConversationSessionState:
    mood: Mood = "neutral"
    fatigue: int = 0
    affinity: int = 50
    _window: deque[ConversationTurn] = field(
        default_factory=lambda: deque(maxlen=6), init=False, repr=False
    )
    _committed_tasks: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self.fatigue = _clamp(self.fatigue, 0, 100)
        self.affinity = _clamp(self.affinity, 0, 100)

    @property
    def completed_window(self) -> tuple[tuple[str, str], ...]:
        return tuple((turn.user_text, turn.final_response) for turn in self._window)

    @property
    def prompt_window(self) -> tuple[tuple[str, str], ...]:
        """Return prompt-safe pairs while retaining raw provenance internally."""

        return tuple((turn.prompt_user_text, turn.final_response) for turn in self._window)

    @property
    def completed_turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._window)

    @property
    def has_private_developer_context(self) -> bool:
        return any(
            turn.actor_role == "developer" or turn.source == "developer_console"
            for turn in self._window
        )

    def commit(
        self,
        *,
        task_id: str,
        user_text: str,
        final_response: str,
        actor_role: str | None = None,
        source: str | None = None,
        mood: Mood | None = None,
        affinity_delta: int = 0,
        update_viewer_state: bool = True,
    ) -> bool:
        if not task_id or task_id in self._committed_tasks:
            return False
        if not user_text.strip() or not final_response.strip():
            return False
        self._window.append(
            ConversationTurn(
                user_text=user_text,
                final_response=final_response,
                task_id=task_id,
                actor_role=actor_role,
                source=source,
            )
        )
        self._committed_tasks.add(task_id)
        if update_viewer_state:
            if mood is not None:
                self.mood = mood
            self.fatigue = _clamp(self.fatigue + 5, 0, 100)
            self.affinity = _clamp(self.affinity + _clamp(affinity_delta, -2, 2), 0, 100)
        return True

    def reset(self) -> None:
        self._window.clear()
        self._committed_tasks.clear()
        self.mood = "neutral"
        self.fatigue = 0
        self.affinity = 50


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


@dataclass(slots=True)
class _RegistryEntry:
    state: ConversationSessionState = field(default_factory=ConversationSessionState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    leases: int = 0


class ConversationSessionRegistry:
    """Bounded LRU registry whose per-scope lock serializes complete graph turns."""

    def __init__(self, *, max_scopes: int = 256) -> None:
        if max_scopes <= 0:
            raise ValueError("max_scopes must be positive")
        self.max_scopes = max_scopes
        self._entries: OrderedDict[ConversationScope, _RegistryEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def scope_count(self) -> int:
        return len(self._entries)

    def peek(self, scope: ConversationScope) -> ConversationSessionState | None:
        entry = self._entries.get(scope)
        return entry.state if entry is not None else None

    @asynccontextmanager
    async def turn(self, scope: ConversationScope) -> AsyncIterator[ConversationSessionState]:
        async with self._lock:
            entry = self._entries.get(scope)
            if entry is None:
                entry = _RegistryEntry()
                self._entries[scope] = entry
            else:
                self._entries.move_to_end(scope)
            entry.leases += 1
            self._evict_idle_entries()

        try:
            await entry.lock.acquire()
            try:
                yield entry.state
            finally:
                entry.lock.release()
        finally:
            async with self._lock:
                entry.leases -= 1
                if scope in self._entries:
                    self._entries.move_to_end(scope)
                self._evict_idle_entries()

    def _evict_idle_entries(self) -> None:
        while len(self._entries) > self.max_scopes:
            evicted = False
            for scope, entry in tuple(self._entries.items()):
                if entry.leases == 0 and not entry.lock.locked():
                    del self._entries[scope]
                    evicted = True
                    break
            if not evicted:
                return
