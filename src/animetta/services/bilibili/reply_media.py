"""Ordered media gate for independently generated livestream replies."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


class BroadcastMediaArbiter:
    """Serialize public media by priority without interrupting an active sentence."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._counter = itertools.count()
        self._waiters: list[tuple[int, int, object]] = []
        self._active: object | None = None

    async def acquire(self, priority: int) -> object:
        token = object()
        waiter = (priority, next(self._counter), token)
        async with self._condition:
            heapq.heappush(self._waiters, waiter)
            try:
                while self._active is not None or self._waiters[0] != waiter:
                    await self._condition.wait()
            except BaseException:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                    heapq.heapify(self._waiters)
                    self._condition.notify_all()
                raise
            heapq.heappop(self._waiters)
            self._active = token
            return token

    async def release(self, token: object) -> None:
        async with self._condition:
            if self._active is token:
                self._active = None
                self._condition.notify_all()


@dataclass(slots=True)
class BroadcastMediaTurn:
    """One idempotent lease in the process-wide livestream media channel."""

    arbiter: BroadcastMediaArbiter
    priority: int
    on_acquired: Callable[[], Awaitable[None]] | None = None
    token: object | None = None
    completed: bool = False

    async def acquire(self) -> None:
        if self.completed or self.token is not None:
            return
        self.token = await self.arbiter.acquire(self.priority)
        if self.on_acquired is None:
            return
        try:
            await self.on_acquired()
        except BaseException:
            await self.arbiter.release(self.token)
            self.token = None
            raise

    async def finish(self) -> None:
        if self.completed:
            return
        self.completed = True
        if self.token is not None:
            await self.arbiter.release(self.token)
            self.token = None

    async def cancel(self) -> None:
        await self.finish()


class OrderedReplyMediaCoordinator:
    """Let reply text/TTS enter the shared output channel in source order."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._next_sequence = 0
        self._active_sequence: int | None = None
        self._cancelled: set[int] = set()

    async def acquire(self, sequence: int) -> None:
        async with self._condition:
            while sequence > self._next_sequence or (
                sequence == self._next_sequence and self._active_sequence not in {None, sequence}
            ):
                await self._condition.wait()
            if sequence == self._next_sequence:
                self._active_sequence = sequence

    async def finish(self, sequence: int) -> None:
        async with self._condition:
            if sequence < self._next_sequence:
                return
            if sequence != self._next_sequence:
                self._cancelled.add(sequence)
                return
            self._active_sequence = None
            self._next_sequence += 1
            while self._next_sequence in self._cancelled:
                self._cancelled.remove(self._next_sequence)
                self._next_sequence += 1
            self._condition.notify_all()

    async def cancel(self, sequence: int) -> None:
        async with self._condition:
            if sequence < self._next_sequence:
                return
            self._cancelled.add(sequence)
            if sequence == self._next_sequence:
                self._active_sequence = None
                while self._next_sequence in self._cancelled:
                    self._cancelled.remove(self._next_sequence)
                    self._next_sequence += 1
            self._condition.notify_all()


@dataclass(slots=True)
class ReplyMediaTurn:
    """One idempotent ticket in the ordered reply media channel."""

    coordinator: OrderedReplyMediaCoordinator
    sequence: int
    broadcast_turn: BroadcastMediaTurn | None = None
    acquired: bool = False
    completed: bool = False

    async def acquire(self) -> None:
        if self.completed or self.acquired:
            return
        await self.coordinator.acquire(self.sequence)
        if self.broadcast_turn is not None:
            await self.broadcast_turn.acquire()
        self.acquired = True

    async def finish(self) -> None:
        if self.completed:
            return
        self.completed = True
        if self.broadcast_turn is not None:
            await self.broadcast_turn.finish()
        await self.coordinator.finish(self.sequence)

    async def cancel(self) -> None:
        if self.completed:
            return
        self.completed = True
        if self.broadcast_turn is not None:
            await self.broadcast_turn.cancel()
        await self.coordinator.cancel(self.sequence)


_CURRENT_REPLY_MEDIA_TURN: ContextVar[ReplyMediaTurn | BroadcastMediaTurn | None] = ContextVar(
    "current_reply_media_turn",
    default=None,
)


@contextmanager
def bind_reply_media_turn(turn: ReplyMediaTurn | BroadcastMediaTurn | None) -> Iterator[None]:
    token = _CURRENT_REPLY_MEDIA_TURN.set(turn)
    try:
        yield
    finally:
        _CURRENT_REPLY_MEDIA_TURN.reset(token)


def has_reply_media_turn() -> bool:
    return _CURRENT_REPLY_MEDIA_TURN.get() is not None


async def acquire_reply_media_turn() -> None:
    turn = _CURRENT_REPLY_MEDIA_TURN.get()
    if turn is not None:
        await turn.acquire()


async def finish_reply_media_turn() -> None:
    turn = _CURRENT_REPLY_MEDIA_TURN.get()
    if turn is not None:
        await turn.finish()
