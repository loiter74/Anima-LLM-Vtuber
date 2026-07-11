"""Orchestrator-owned bounded conversation continuity state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Literal

Mood = Literal["neutral", "bright", "tired", "irritated"]


@dataclass(slots=True)
class ConversationSessionState:
    mood: Mood = "neutral"
    fatigue: int = 0
    affinity: int = 50
    _window: deque[tuple[str, str]] = field(
        default_factory=lambda: deque(maxlen=6), init=False, repr=False
    )
    _committed_tasks: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self.fatigue = _clamp(self.fatigue, 0, 100)
        self.affinity = _clamp(self.affinity, 0, 100)

    @property
    def completed_window(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._window)

    def commit(
        self,
        *,
        task_id: str,
        user_text: str,
        final_response: str,
        mood: Mood | None = None,
        affinity_delta: int = 0,
    ) -> bool:
        if not task_id or task_id in self._committed_tasks:
            return False
        if not user_text.strip() or not final_response.strip():
            return False
        self._window.append((user_text, final_response))
        self._committed_tasks.add(task_id)
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
