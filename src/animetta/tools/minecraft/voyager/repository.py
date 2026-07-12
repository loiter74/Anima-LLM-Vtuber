"""Persistence boundary for Voyager status and committed task checkpoints."""

from __future__ import annotations

from typing import Protocol

from .contracts import VoyagerCheckpoint, VoyagerStatus


class VoyagerRepository(Protocol):
    async def save_status(self, status: VoyagerStatus) -> None: ...

    async def load_status(self) -> VoyagerStatus | None: ...

    async def commit_checkpoint(self, checkpoint: VoyagerCheckpoint) -> None: ...

    async def last_checkpoint(self, session_id: str) -> VoyagerCheckpoint | None: ...


class InMemoryVoyagerRepository:
    def __init__(self) -> None:
        self._status: VoyagerStatus | None = None
        self._checkpoints: dict[str, VoyagerCheckpoint] = {}

    async def save_status(self, status: VoyagerStatus) -> None:
        self._status = status.model_copy(deep=True)

    async def load_status(self) -> VoyagerStatus | None:
        return self._status.model_copy(deep=True) if self._status else None

    async def commit_checkpoint(self, checkpoint: VoyagerCheckpoint) -> None:
        self._checkpoints[checkpoint.session_id] = checkpoint.model_copy(deep=True)

    async def last_checkpoint(self, session_id: str) -> VoyagerCheckpoint | None:
        checkpoint = self._checkpoints.get(session_id)
        return checkpoint.model_copy(deep=True) if checkpoint else None
