from __future__ import annotations

"""Tests for AsyncScheduler — periodic task execution, lifecycle, metrics, timeout."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from animetta.orchestration.graph.scheduler import AsyncScheduler, ScheduledTask, TaskMetrics

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def scheduler():
    """Return a fresh AsyncScheduler."""
    return AsyncScheduler()


@pytest.fixture
def immediate_scheduler_sleep():
    """Yield to asyncio without waiting for scheduler wall-clock intervals."""
    real_sleep = asyncio.sleep

    async def immediate_sleep(_delay: float) -> None:
        await real_sleep(0)

    return immediate_sleep


# ── TaskMetrics ─────────────────────────────────────────────


class TestTaskMetrics:
    """TaskMetrics dataclass tracks per-task execution stats."""

    def test_default_values(self):
        """New TaskMetrics starts at zero."""
        m = TaskMetrics(name="test")
        assert m.name == "test"
        assert m.last_run is None
        assert m.last_duration is None
        assert m.success_count == 0
        assert m.failure_count == 0
        assert m.total_runs == 0

    def test_name_set_in_post_init(self):
        """ScheduledTask.__post_init__ propagates name to metrics."""
        task = ScheduledTask(
            name="my-task",
            func=AsyncMock(),
            interval=10.0,
            timeout=5.0,
        )
        assert task.metrics.name == "my-task"


# ── ScheduledTask ───────────────────────────────────────────


class TestScheduledTask:
    """ScheduledTask holds task metadata."""

    def test_creation(self):
        """A ScheduledTask stores all fields."""

        async def dummy():
            pass

        task = ScheduledTask(
            name="unit",
            func=dummy,
            interval=30.0,
            timeout=10.0,
        )
        assert task.name == "unit"
        assert task.func is dummy
        assert task.interval == 30.0
        assert task.timeout == 10.0
        assert task._task is None
        assert not task._cancel_event.is_set()


# ── add_task / remove_task ──────────────────────────────────


class TestTaskRegistration:
    """Adding and removing tasks."""

    def test_add_task_stores_it(self, scheduler):
        """After add_task, the task is in _tasks."""

        async def dummy():
            pass

        scheduler.add_task("test", dummy, interval=10.0)
        assert "test" in scheduler._tasks
        assert scheduler._tasks["test"].func is dummy

    def test_add_task_warns_on_duplicate(self, scheduler):
        """Adding a task with an existing name logs a warning."""

        async def dummy():
            pass

        with patch("animetta.orchestration.graph.scheduler.logger") as mock_logger:
            scheduler.add_task("dup", dummy, interval=10.0)
            scheduler.add_task("dup", dummy, interval=20.0)
            mock_logger.warning.assert_called()
            assert "already registered" in str(mock_logger.warning.call_args)

    def test_remove_task_removes_it(self, scheduler):
        """Removing a task clears it from _tasks."""

        async def dummy():
            pass

        scheduler.add_task("gone", dummy, interval=10.0)
        scheduler.remove_task("gone")
        assert "gone" not in scheduler._tasks

    def test_remove_task_warns_on_missing(self, scheduler):
        """Removing a non-existent task logs a warning."""
        with patch("animetta.orchestration.graph.scheduler.logger") as mock_logger:
            scheduler.remove_task("nope")
            mock_logger.warning.assert_called()
            assert "not found" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_remove_task_cancels_running(self, scheduler):
        """Removing a task that is running cancels its asyncio.Task."""

        async def never_ending():
            await asyncio.Event().wait()

        scheduler.add_task("run", never_ending, interval=1.0)
        task_wrapper = scheduler._tasks["run"]
        task_wrapper._task = asyncio.create_task(never_ending())

        scheduler.remove_task("run")

        assert "run" not in scheduler._tasks
        assert task_wrapper._cancel_event.is_set()

    def test_add_task_default_timeout(self, scheduler):
        """Default timeout is 300 seconds."""

        async def dummy():
            pass

        scheduler.add_task("default", dummy, interval=10.0)
        assert scheduler._tasks["default"].timeout == 300.0


# ── Start / Stop lifecycle ──────────────────────────────────


class TestLifecycle:
    """Scheduler start/stop."""

    @pytest.mark.asyncio
    async def test_start_and_stop_update_running_state(self, scheduler):
        """Start and stop update the scheduler lifecycle state."""
        await scheduler.start()
        assert scheduler._running
        await scheduler.stop()
        assert not scheduler._running

    @pytest.mark.asyncio
    async def test_start_twice_is_idempotent(self, scheduler):
        """Starting an already-running scheduler logs a warning."""
        with patch("animetta.orchestration.graph.scheduler.logger") as mock_logger:
            await scheduler.start()
            await scheduler.start()
            mock_logger.warning.assert_called()
            assert "Already running" in str(mock_logger.warning.call_args)
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, scheduler):
        """Stopping a scheduler that was never started is safe."""
        await scheduler.stop()
        assert not scheduler._running

    @pytest.mark.asyncio
    async def test_stop_graceful_shutdown(self, scheduler):
        """Stop cancels tasks and main loop cleanly."""

        async def quick():
            pass

        scheduler.add_task("q", quick, interval=0.05)
        await scheduler.start()
        await scheduler.stop()
        # Verify main loop is done
        if scheduler._main_loop_task:
            assert scheduler._main_loop_task.done()


# ── Task execution ──────────────────────────────────────────


class TestTaskExecution:
    """Task running and interval behaviour."""

    @pytest.mark.asyncio
    async def test_task_runs_at_interval(self, scheduler, immediate_scheduler_sleep):
        """Task executes multiple times at the configured interval."""
        call_count = 0
        done = asyncio.Event()

        async def counter():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                done.set()

        scheduler.add_task("cnt", counter, interval=0.05, timeout=5)
        with patch(
            "animetta.orchestration.graph.scheduler.asyncio.sleep",
            new=immediate_scheduler_sleep,
        ):
            await scheduler.start()
            try:
                await asyncio.wait_for(done.wait(), timeout=1)
            finally:
                await scheduler.stop()

        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_task_execution_failure(self, scheduler, immediate_scheduler_sleep):
        """A failing task logs the error and increments failure_count."""
        fail_count = 0
        recovered = asyncio.Event()

        async def flaky():
            nonlocal fail_count
            fail_count += 1
            if fail_count == 1:
                msg = "something went wrong"
                raise RuntimeError(msg)
            recovered.set()

        scheduler.add_task("flaky", flaky, interval=0.05, timeout=5)

        with (
            patch("animetta.orchestration.graph.scheduler.logger") as mock_logger,
            patch(
                "animetta.orchestration.graph.scheduler.asyncio.sleep",
                new=immediate_scheduler_sleep,
            ),
        ):
            await scheduler.start()
            try:
                await asyncio.wait_for(recovered.wait(), timeout=1)
            finally:
                await scheduler.stop()

            mock_logger.error.assert_called()
            assert "execution error" in str(mock_logger.error.call_args)

        metrics = scheduler.get_task_metrics("flaky")
        assert metrics is not None
        assert metrics.failure_count == 1


# ── Metrics ─────────────────────────────────────────────────


class TestMetrics:
    """Metrics retrieval."""

    def test_get_metrics_empty(self, scheduler):
        """No tasks → empty list."""
        assert scheduler.get_metrics() == []

    def test_get_metrics_after_adding_tasks(self, scheduler):
        """Tasks appear in metrics list."""

        async def a():
            pass

        async def b():
            pass

        scheduler.add_task("a", a, interval=10.0)
        scheduler.add_task("b", b, interval=20.0)

        metrics = scheduler.get_metrics()
        names = {m.name for m in metrics}
        assert names == {"a", "b"}

    def test_get_task_metrics_exists(self, scheduler):
        """Looking up a known task returns its metrics."""

        async def dummy():
            pass

        scheduler.add_task("known", dummy, interval=10.0)

        m = scheduler.get_task_metrics("known")
        assert m is not None
        assert m.name == "known"

    def test_get_task_metrics_missing(self, scheduler):
        """Looking up an unknown task returns None."""
        assert scheduler.get_task_metrics("ghost") is None


# ── _execute_with_timeout (unit) ────────────────────────────


class TestExecuteWithTimeout:
    """Direct unit tests for _execute_with_timeout."""

    @pytest.mark.asyncio
    async def test_successful_execution(self, scheduler):
        """Successful call updates metrics correctly."""
        task = ScheduledTask(
            name="unit-success",
            func=AsyncMock(return_value="ok"),
            interval=1.0,
            timeout=5.0,
        )

        await scheduler._execute_with_timeout(task)

        assert task.metrics.total_runs == 1
        assert task.metrics.success_count == 1
        assert task.metrics.failure_count == 0
        assert task.metrics.last_run is not None
        assert task.metrics.last_duration is not None
        assert task.metrics.last_duration > 0

    @pytest.mark.asyncio
    async def test_timeout_increments_failure(self, scheduler):
        """Timed-out execution increments failure_count."""

        async def never():
            await asyncio.sleep(999)

        task = ScheduledTask(
            name="unit-timeout",
            func=never,
            interval=1.0,
            timeout=0.05,
        )

        await scheduler._execute_with_timeout(task)

        assert task.metrics.total_runs == 1
        assert task.metrics.success_count == 0
        assert task.metrics.failure_count == 1

    @pytest.mark.asyncio
    async def test_cancelled_error_raised(self, scheduler):
        """CancelledError is re-raised (not counted as failure)."""

        async def cancelling():
            raise asyncio.CancelledError()

        task = ScheduledTask(
            name="unit-cancel",
            func=cancelling,
            interval=1.0,
            timeout=5.0,
        )

        with pytest.raises(asyncio.CancelledError):
            await scheduler._execute_with_timeout(task)
