from __future__ import annotations

"""Tests for Live2DActionQueue enqueue/dequeue and all overflow/replace policies."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from animetta.services.live2d.action_queue import (
    ActionMessage,
    Live2DActionMutex,
    Live2DActionQueue,
    OverflowPolicy,
    QueuePolicy,
)


class TestActionMessage:
    """ActionMessage data class tests."""

    def test_create_action_message(self):
        msg = ActionMessage(
            action_id="test_1",
            action={"type": "expression", "name": "happy"},
            duration_sec=0.5,
            queue_policy="append",
        )
        assert msg.action_id == "test_1"
        assert msg.action["type"] == "expression"
        assert msg.duration_sec == 0.5
        assert msg.queue_policy == QueuePolicy.APPEND

    def test_queue_policy_enum_conversion(self):
        msg = ActionMessage(
            action_id="test",
            action={},
            queue_policy="replace",
        )
        assert msg.queue_policy == QueuePolicy.REPLACE

    def test_queue_policy_invalid_value(self):
        with pytest.raises(ValueError):
            ActionMessage(
                action_id="test",
                action={},
                queue_policy="invalid_policy",
            )


class TestLive2DActionQueueBasic:
    """Basic Live2DActionQueue operations."""

    @pytest.fixture
    def queue(self):
        return Live2DActionQueue()

    def test_init_defaults(self):
        q = Live2DActionQueue()
        assert q.max_size == 120
        assert q.overflow_policy == OverflowPolicy.DROP_OLDEST
        assert q.queue == []
        assert q.is_processing is False
        assert q.current_action is None

    def test_init_custom(self):
        q = Live2DActionQueue(max_size=10, overflow_policy=OverflowPolicy.REJECT)
        assert q.max_size == 10
        assert q.overflow_policy == OverflowPolicy.REJECT

    def test_queue_size_property(self):
        q = Live2DActionQueue()
        assert q.queue_size == 0
        q.queue.append(ActionMessage("a", {}, queue_policy="append"))
        assert q.queue_size == 1

    def test_clear_queue(self):
        q = Live2DActionQueue()
        q.queue.append(ActionMessage("a", {}, queue_policy="append"))
        q.queue.append(ActionMessage("b", {}, queue_policy="append"))
        q.clear()
        assert q.queue_size == 0


class TestLive2DActionQueueEnqueue:
    """Enqueue behavior tests."""

    @pytest.mark.asyncio
    async def test_enqueue_append(self):
        q = Live2DActionQueue()
        result = await q.enqueue(ActionMessage("a", {"type": "test"}, queue_policy="append"))
        assert result["ok"] is True
        assert q.queue_size == 1

    @pytest.mark.asyncio
    async def test_enqueue_replace_clears_queue(self):
        q = Live2DActionQueue()
        q.queue.append(ActionMessage("old1", {}, queue_policy="append"))
        q.queue.append(ActionMessage("old2", {}, queue_policy="append"))

        result = await q.enqueue(ActionMessage("new", {}, queue_policy="replace"))
        assert result["ok"] is True
        assert q.queue_size == 1
        assert q.queue[0].action_id == "new"

    @pytest.mark.asyncio
    async def test_enqueue_interrupt(self):
        q = Live2DActionQueue()
        q.queue.append(ActionMessage("old1", {}, queue_policy="append"))

        result = await q.enqueue(ActionMessage("interrupt", {}, queue_policy="interrupt"))
        assert result["ok"] is True
        assert q.queue_size == 1
        assert q.queue[0].action_id == "interrupt"

    @pytest.mark.asyncio
    async def test_process_queue_with_multiple_actions(self):

        # Use a zero-cooldown mutex so actions process quickly
        q = Live2DActionQueue(mutex=Live2DActionMutex(cooldown_ms=0))
        callback = AsyncMock()
        q.set_execute_callback(callback)

        await q.enqueue(
            ActionMessage("a", {"type": "test"}, duration_sec=0.001, queue_policy="append")
        )
        await q.enqueue(
            ActionMessage("b", {"type": "test"}, duration_sec=0.001, queue_policy="append")
        )

        await asyncio.sleep(0.2)
        assert callback.call_count == 2

    @pytest.mark.asyncio
    async def test_process_queue_stops_when_empty(self):

        q = Live2DActionQueue()
        q.set_execute_callback(AsyncMock())

        await q.enqueue(
            ActionMessage("a", {"type": "test"}, duration_sec=0.001, queue_policy="append")
        )
        await asyncio.sleep(0.1)
        # After processing, is_processing should be False
        assert q.is_processing is False

    @pytest.mark.asyncio
    async def test_stop_queue(self):

        q = Live2DActionQueue()
        q.set_execute_callback(AsyncMock())

        await q.enqueue(
            ActionMessage("a", {"type": "test"}, duration_sec=1.0, queue_policy="append")
        )
        await q.stop()
        assert q.is_processing is False
        assert q.queue_size == 0

    @pytest.mark.asyncio
    async def test_no_callback_logs_warning(self):
        """Enqueuing without a callback should not crash."""

        q = Live2DActionQueue()
        # Enqueue and stop - should not raise
        await q.enqueue(
            ActionMessage("a", {"type": "test"}, duration_sec=0.001, queue_policy="append")
        )
        await q.stop()
        assert q.is_processing is False
