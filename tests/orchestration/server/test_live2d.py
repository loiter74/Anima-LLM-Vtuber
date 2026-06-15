from __future__ import annotations

"""Tests for Live2DManager — action queue, policy, callback execution, lazy init."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.orchestration.server.live2d import Live2DManager
from animetta.services.live2d.action_queue import QueuePolicy

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def live2d_manager():
    """Fresh Live2DManager for each test."""
    return Live2DManager()


@pytest.fixture
def mock_action_message():
    """Factory for creating mock ActionMessage data."""
    def _make(action_data=None, action_id="test_action", queue_policy="append", duration=0.5):
        return {
            "action_data": action_data or {"expression": "smile", "intensity": 0.8},
            "action_id": action_id,
            "queue_policy": queue_policy,
            "duration": duration,
        }
    return _make


@pytest.fixture
def mock_queue():
    """Mock Live2DActionQueue with async enqueue."""
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value={"enqueued": True, "action_id": "test"})
    queue.set_execute_callback = MagicMock()
    return queue


# ── Live2DManager — Init ───────────────────────────────────────────


class TestLive2DManagerInit:
    """Construction and default state."""

    def test_init_sets_defaults(self, live2d_manager):
        """__init__ sets _action_queue and _execute_callback to None."""
        assert live2d_manager._action_queue is None
        assert live2d_manager._execute_callback is None

    def test_is_initialized_false_initially(self, live2d_manager):
        """is_initialized returns False before lazy init."""
        assert live2d_manager.is_initialized() is False

    def test_is_initialized_true_after_access(self, live2d_manager):
        """is_initialized returns True after accessing action_queue."""
        with patch("animetta.orchestration.server.live2d.Live2DActionQueue") as mock_q:
            mock_q.return_value = MagicMock()
            _ = live2d_manager.action_queue
            assert live2d_manager.is_initialized() is True


# ── Live2DManager — action_queue (lazy init) ───────────────────────


class TestLazyInit:
    """Lazy initialization of the action queue."""

    def test_action_queue_lazy_init(self, live2d_manager):
        """action_queue lazily creates Live2DActionQueue on first access."""
        with patch("animetta.orchestration.server.live2d.Live2DActionQueue") as mock_q:
            mock_instance = MagicMock()
            mock_q.return_value = mock_instance

            queue = live2d_manager.action_queue

            assert queue is mock_instance
            mock_q.assert_called_once_with()

    def test_action_queue_caches_instance(self, live2d_manager):
        """Second access returns the same cached instance."""
        with patch("animetta.orchestration.server.live2d.Live2DActionQueue") as mock_q:
            mock_q.return_value = MagicMock(name="cq")

            q1 = live2d_manager.action_queue
            q2 = live2d_manager.action_queue

            assert q1 is q2
            mock_q.assert_called_once()

    def test_lazy_init_logs_message(self, live2d_manager):
        """Lazy init logs an info message."""
        with patch("animetta.orchestration.server.live2d.logger") as mock_logger, \
             patch("animetta.services.live2d.Live2DActionQueue") as mock_q:
            mock_q.return_value = MagicMock()
            _ = live2d_manager.action_queue
            mock_logger.info.assert_called_once_with("[Live2D] Action queue initialized")


# ── Live2DManager — set_execute_callback ───────────────────────────


class TestSetExecuteCallback:
    """Callback registration."""

    def test_set_execute_callback_stores_callback(self, live2d_manager):
        """set_execute_callback stores the callback."""
        async def mock_cb(action):
            pass

        live2d_manager.set_execute_callback(mock_cb)
        assert live2d_manager._execute_callback is mock_cb

    def test_set_execute_callback_propagates_to_queue_when_initialized(self, live2d_manager):
        """When queue is already initialized, callback is propagated."""
        queue = MagicMock()
        live2d_manager._action_queue = queue

        async def mock_cb(action):
            pass

        live2d_manager.set_execute_callback(mock_cb)
        queue.set_execute_callback.assert_called_once_with(mock_cb)

    def test_set_execute_callback_skips_queue_when_not_initialized(self, live2d_manager):
        """When queue is not initialized, callback is stored but not propagated."""
        async def mock_cb(action):
            pass

        live2d_manager.set_execute_callback(mock_cb)
        assert live2d_manager._execute_callback is mock_cb
        # No error when queue is None


# ── Live2DManager — enqueue_action ─────────────────────────────────


class TestEnqueueAction:
    """Action enqueue with different policies."""

    @pytest.mark.asyncio
    async def test_enqueue_append_policy(self, live2d_manager, mock_queue, mock_action_message):
        """Enqueue with 'append' policy calls queue.enqueue."""
        live2d_manager._action_queue = mock_queue
        params = mock_action_message(queue_policy="append")

        result = await live2d_manager.enqueue_action(**params)

        assert result == {"enqueued": True, "action_id": "test"}
        mock_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_replace_policy(self, live2d_manager, mock_queue, mock_action_message):
        """Enqueue with 'replace' policy."""
        live2d_manager._action_queue = mock_queue
        params = mock_action_message(queue_policy="replace")

        result = await live2d_manager.enqueue_action(**params)

        assert result["enqueued"] is True
        mock_queue.enqueue.assert_called_once()
        # Verify ActionMessage was created with correct policy (enum value)
        call_args = mock_queue.enqueue.call_args[0][0]
        assert call_args.queue_policy.value == "replace"

    @pytest.mark.asyncio
    async def test_enqueue_interrupt_policy(self, live2d_manager, mock_queue, mock_action_message):
        """Enqueue with 'interrupt' policy."""
        live2d_manager._action_queue = mock_queue
        params = mock_action_message(queue_policy="interrupt")

        result = await live2d_manager.enqueue_action(**params)

        assert result["enqueued"] is True
        call_args = mock_queue.enqueue.call_args[0][0]
        assert call_args.queue_policy.value == "interrupt"

    @pytest.mark.asyncio
    async def test_enqueue_action_creates_action_message(self, live2d_manager):
        """enqueue_action creates an ActionMessage and forwards it to queue.enqueue."""
        action_data = {"expression": "wave", "intensity": 0.5}
        live2d_manager._action_queue = MagicMock()
        live2d_manager._action_queue.enqueue = AsyncMock(return_value={"ok": True})

        await live2d_manager.enqueue_action(
            action_data=action_data,
            action_id="wave_hello",
            queue_policy="append",
            duration=1.0,
        )

        live2d_manager._action_queue.enqueue.assert_called_once()
        call_arg = live2d_manager._action_queue.enqueue.call_args[0][0]
        assert call_arg.action_id == "wave_hello"
        assert call_arg.action == action_data
        assert call_arg.duration_sec == 1.0

    @pytest.mark.asyncio
    async def test_enqueue_triggers_lazy_init(self, live2d_manager, mock_action_message):
        """enqueue_action triggers lazy initialization of action_queue."""
        with patch("animetta.orchestration.server.live2d.Live2DActionQueue") as mock_q:
            mock_instance = MagicMock()
            mock_instance.enqueue = AsyncMock(return_value={"ok": True})
            mock_q.return_value = mock_instance

            params = mock_action_message()
            result = await live2d_manager.enqueue_action(**params)

            assert result["ok"] is True
            assert live2d_manager.is_initialized() is True
            mock_q.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_default_policy_is_append(self, live2d_manager, mock_action_message):
        """Default queue policy is 'append'."""
        with patch("animetta.orchestration.server.live2d.Live2DActionQueue") as mock_q:
            mock_instance = MagicMock()
            mock_instance.enqueue = AsyncMock(return_value={"ok": True})
            mock_q.return_value = mock_instance

            params = mock_action_message()  # No queue_policy specified
            await live2d_manager.enqueue_action(**params)

            call_arg = mock_instance.enqueue.call_args[0][0]
            assert call_arg.queue_policy == QueuePolicy.APPEND


# ── Live2DManager — action queue callback execution (integration) ──


class TestActionCallbackExecution:
    """End-to-end: enqueue → callback execution."""

    @pytest.mark.asyncio
    async def test_execute_callback_receives_action(self, live2d_manager, mock_queue):
        """When set, the execute callback is stored on the queue."""
        live2d_manager._action_queue = mock_queue

        async def capture_callback(action):
            pass

        live2d_manager.set_execute_callback(capture_callback)
        mock_queue.set_execute_callback.assert_called_once_with(capture_callback)

    @pytest.mark.asyncio
    async def test_enqueue_returns_result_dict(self, live2d_manager, mock_queue):
        """enqueue_action returns the dict from queue.enqueue."""
        live2d_manager._action_queue = mock_queue
        expected = {"ok": True, "action_id": "test", "queue_size": 1}
        mock_queue.enqueue = AsyncMock(return_value=expected)

        result = await live2d_manager.enqueue_action(
            action_data={"expression": "smile"},
            action_id="smile",
        )

        assert result == expected
