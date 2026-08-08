from __future__ import annotations

"""Tests for Live2DManager — action enqueue lifecycle, callback propagation, stop/resume cycle."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.orchestration.server.live2d import Live2DManager
from animetta.services.live2d.action_queue import QueuePolicy

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def live2d_manager():
    """Fresh Live2DManager for each test."""
    return Live2DManager()


# ── Lifecycle: Callback Propagation through Lazy Init ────────────────


class TestCallbackPropagationLifecycle:
    """Callback propagation lifecycle — must be set after queue init."""

    def test_callback_stored_before_init(self, live2d_manager):
        """Setting callback before queue init stores it on manager but does NOT propagate yet."""

        async def my_callback(action):
            pass

        live2d_manager.set_execute_callback(my_callback)
        assert live2d_manager._execute_callback is my_callback
        # Queue doesn't exist yet, so callback is only stored locally
        assert live2d_manager._action_queue is None

    def test_callback_propagated_when_set_after_init(self, live2d_manager):
        """Setting callback after queue exists propagates to the queue."""
        queue = MagicMock()
        live2d_manager._action_queue = queue

        async def my_callback(action):
            pass

        live2d_manager.set_execute_callback(my_callback)
        queue.set_execute_callback.assert_called_once_with(my_callback)

    def test_callback_not_double_set(self, live2d_manager):
        """When callback is set after queue init, it propagates exactly once."""
        queue = MagicMock()
        live2d_manager._action_queue = queue

        async def my_callback(action):
            pass

        live2d_manager.set_execute_callback(my_callback)
        queue.set_execute_callback.assert_called_once_with(my_callback)

    def test_is_initialized_reflects_queue_state(self, live2d_manager):
        """is_initialized tracks whether queue has been created."""
        assert live2d_manager.is_initialized() is False

        queue = MagicMock()
        live2d_manager._action_queue = queue
        assert live2d_manager.is_initialized() is True

        live2d_manager._action_queue = None
        assert live2d_manager.is_initialized() is False


# ── Lifecycle: Enqueue → Process → Complete ─────────────────────────


class TestEnqueueProcessLifecycle:
    """End-to-end: enqueue actions and verify they are processed."""

    @pytest.mark.asyncio
    async def test_enqueue_single_action_triggers_processing(self, live2d_manager):
        """Enqueuing one action starts background processing."""
        # Must init queue BEFORE setting callback so it propagates
        _ = live2d_manager.action_queue

        callback = AsyncMock()
        live2d_manager.set_execute_callback(callback)

        result = await live2d_manager.enqueue_action(
            action_data={"type": "expression", "name": "happy"},
            action_id="happy_1",
            duration=0.01,
        )
        assert result["ok"] is True

        await live2d_manager.action_queue._process_task

        # Callback should have been called at least once
        assert callback.call_count >= 1

        # After processing, queue should be idle
        queue = live2d_manager.action_queue
        assert queue.queue_size == 0

    @pytest.mark.asyncio
    async def test_enqueue_multiple_actions_sequential(self, live2d_manager):
        """Multiple enqueued actions are all processed in order."""
        # Init queue first, then set callback so it propagates to the queue
        live2d_manager.action_queue.mutex.cooldown_ms = 0

        executed = []

        async def track_callback(action):
            executed.append(action.action_id)

        live2d_manager.set_execute_callback(track_callback)

        for i in range(3):
            await live2d_manager.enqueue_action(
                action_data={"type": "test", "index": i},
                action_id=f"action_{i}",
                duration=0.01,
            )
            if i == 0:
                await asyncio.sleep(0)

        process_task = live2d_manager.action_queue._process_task
        await process_task
        assert len(executed) == 3
        assert executed == ["action_0", "action_1", "action_2"]

    @pytest.mark.asyncio
    async def test_enqueue_while_processing(self, live2d_manager):
        """Actions enqueued while processing are handled by the queue."""
        live2d_manager.action_queue.mutex.cooldown_ms = 0

        callback = AsyncMock()
        live2d_manager.set_execute_callback(callback)

        # Enqueue first action
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="first",
            duration=0.02,
        )
        await asyncio.sleep(0)
        process_task = live2d_manager.action_queue._process_task
        # Enqueue second while first is (potentially) processing
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="second",
            duration=0.01,
        )

        await process_task
        # Both should have been executed
        assert callback.call_count >= 2

    @pytest.mark.asyncio
    async def test_queue_size_after_multiple_enqueues(self, live2d_manager):
        """queue_size property reflects pending actions."""
        # Pre-init the queue but set execute callback to None
        _ = live2d_manager.action_queue

        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="a1",
            duration=0.5,
        )
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="a2",
            duration=0.5,
        )

        # Both should be in queue (no callback, so they pile up without being "executed")
        q = live2d_manager.action_queue
        assert q.queue_size >= 1  # At least one pending

        # Stop to clean up
        await q.stop()


# ── Lifecycle: Stop / Clear / Restart ───────────────────────────────


class TestStopClearLifecycle:
    """Stop and clear operations within the lifecycle."""

    @pytest.mark.asyncio
    async def test_stop_then_enqueue_restarts_processing(self, live2d_manager):
        """After stopping the queue, new enqueues restart processing."""
        live2d_manager.action_queue.mutex.cooldown_ms = 0

        callback = AsyncMock()
        live2d_manager.set_execute_callback(callback)

        # Enqueue and stop
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="before_stop",
            duration=0.01,
        )
        await live2d_manager.action_queue._process_task
        await live2d_manager.action_queue.stop()

        # Verify stopped
        assert live2d_manager.action_queue.is_processing is False
        assert live2d_manager.action_queue.queue_size == 0

        # Enqueue again — should restart
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="after_stop",
            duration=0.01,
        )
        await live2d_manager.action_queue._process_task

        # Both actions should have been processed
        called_ids = [c.args[0].action_id for c in callback.call_args_list]
        assert called_ids == ["before_stop", "after_stop"]

    @pytest.mark.asyncio
    async def test_clear_empties_queue(self, live2d_manager):
        """clear() removes all pending actions."""
        _ = live2d_manager.action_queue

        # Enqueue several actions without processing (no callback)
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="a1",
            duration=0.5,
        )
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="a2",
            duration=0.5,
        )

        assert live2d_manager.action_queue.queue_size >= 1

        live2d_manager.action_queue.clear()
        assert live2d_manager.action_queue.queue_size == 0

        # Clean up any running task
        await live2d_manager.action_queue.stop()

    @pytest.mark.asyncio
    async def test_no_callback_enqueue_does_not_crash(self, live2d_manager):
        """Enqueuing without callback set should not raise errors."""
        result = await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="nocb",
            duration=0.01,
        )
        assert result["ok"] is True

        # Stop cleanly
        await live2d_manager.action_queue.stop()

    @pytest.mark.asyncio
    async def test_enqueue_with_minimal_action_data(self, live2d_manager):
        """Enqueuing with empty action_data dict should succeed."""
        result = await live2d_manager.enqueue_action(
            action_data={},
            action_id="minimal",
        )
        assert result["ok"] is True
        await live2d_manager.action_queue.stop()

    @pytest.mark.asyncio
    async def test_multiple_stop_calls_do_not_crash(self, live2d_manager):
        """Calling stop() multiple times is safe."""
        _ = live2d_manager.action_queue
        await live2d_manager.action_queue.stop()
        await live2d_manager.action_queue.stop()  # should not raise


# ── Lifecycle: Replace/Interrupt ─────────────────────────────────────


class TestReplaceInterruptLifecycle:
    """REPLACE and INTERRUPT policies during processing lifecycle."""

    @pytest.mark.asyncio
    async def test_replace_clears_pending_and_keeps_one(self, live2d_manager):
        """REPLACE policy clears queue and enqueues only the new action."""
        _ = live2d_manager.action_queue

        # Enqueue with APPEND first
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="old1",
            duration=0.5,
            queue_policy="append",
        )
        await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="old2",
            duration=0.5,
            queue_policy="append",
        )

        # Now REPLACE should clear those and leave only the new one
        result = await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="new_only",
            duration=0.01,
            queue_policy="replace",
        )
        assert result["ok"] is True

        q = live2d_manager.action_queue
        # Should have no more than 1 (the new action)
        assert q.queue_size <= 1

        await q.stop()

    @pytest.mark.asyncio
    async def test_default_queue_policy_is_append(self, live2d_manager):
        """Default queue_policy in Live2DManager.enqueue_action is 'append'."""
        with patch.object(
            live2d_manager.action_queue, "enqueue", new=AsyncMock(return_value={"ok": True})
        ):
            await live2d_manager.enqueue_action(
                action_data={"type": "test"},
                action_id="default_policy",
            )
            call_arg = live2d_manager.action_queue.enqueue.call_args[0][0]
            assert call_arg.queue_policy == QueuePolicy.APPEND


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    """Unusual scenarios for Live2DManager."""

    def test_manager_init_state_is_clean(self, live2d_manager):
        """Fresh manager has no queue and no callback."""
        assert live2d_manager._action_queue is None
        assert live2d_manager._execute_callback is None
        assert live2d_manager.is_initialized() is False

    def test_callback_can_be_none(self, live2d_manager):
        """Setting callback to None is valid."""
        live2d_manager.set_execute_callback(None)
        assert live2d_manager._execute_callback is None

    @pytest.mark.asyncio
    async def test_enqueue_with_very_long_duration(self, live2d_manager):
        """Very long duration actions are accepted."""
        result = await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="long_one",
            duration=999.0,
        )
        assert result["ok"] is True
        await live2d_manager.action_queue.stop()

    @pytest.mark.asyncio
    async def test_enqueue_with_empty_action_id(self, live2d_manager):
        """Empty action_id is valid."""
        result = await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="",
        )
        assert result["ok"] is True
        await live2d_manager.action_queue.stop()

    @pytest.mark.asyncio
    async def test_enqueue_result_contains_queue_size(self, live2d_manager):
        """enqueue result dict includes queue_size."""
        _ = live2d_manager.action_queue

        callback = AsyncMock()
        live2d_manager.set_execute_callback(callback)

        result = await live2d_manager.enqueue_action(
            action_data={"type": "test"},
            action_id="size_check",
            duration=0.01,
        )
        assert "queue_size" in result
        assert isinstance(result["queue_size"], int)
        await live2d_manager.action_queue._process_task
