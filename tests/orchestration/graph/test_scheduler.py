from __future__ import annotations

"""Tests for AsyncScheduler — periodic task execution, lifecycle, metrics, timeout."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from animetta.orchestration.graph.scheduler import AsyncScheduler, ScheduledTask, TaskMetrics

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def scheduler():
    """Return a fresh AsyncScheduler."""
    return AsyncScheduler()


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

    def test_after_successful_run(self):
        """After a success, counters and timestamps update."""
        m = TaskMetrics(name="test")
        m.total_runs = 1
        m.success_count = 1
        now = time.time()
        m.last_run = now
        m.last_duration = 0.5

        assert m.total_runs == 1
        assert m.success_count == 1
        assert m.last_run == now
        assert m.last_duration == 0.5

    def test_after_failure(self):
        """After a failure, failure_count increments."""
        m = TaskMetrics(name="test")
        m.total_runs = 1
        m.failure_count = 1
        assert m.total_runs == 1
        assert m.failure_count == 1

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

    def test_post_init_sets_metrics_name(self):
        """__post_init__ synchronises name into metrics."""
        task = ScheduledTask(
            name="sync-test",
            func=AsyncMock(),
            interval=5.0,
            timeout=2.0,
        )
        assert task.metrics.name == "sync-test"


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
    async def test_start_sets_running(self, scheduler):
        """After start, _running is True."""
        await scheduler.start()
        assert scheduler._running
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, scheduler):
        """After stop, _running is False."""
        await scheduler.start()
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
    async def test_start_with_tasks_runs_them(self, scheduler):
        """Started scheduler executes registered tasks."""
        executed = asyncio.Event()

        async def task_func():
            executed.set()

        scheduler.add_task("go", task_func, interval=0.05, timeout=5)
        await scheduler.start()

        try:
            await asyncio.wait_for(executed.wait(), timeout=2)
            assert executed.is_set()
        finally:
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
    async def test_task_runs_at_interval(self, scheduler):
        """Task executes multiple times at the configured interval."""
        call_count = 0
        done = asyncio.Event()

        async def counter():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                done.set()

        scheduler.add_task("cnt", counter, interval=0.05, timeout=5)
        await scheduler.start()

        try:
            await asyncio.wait_for(done.wait(), timeout=5)
            assert call_count >= 3
        finally:
            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_task_execution_failure(self, scheduler):
        """A failing task logs the error and increments failure_count."""
        fail_count = 0

        async def flaky():
            nonlocal fail_count
            fail_count += 1
            if fail_count == 1:
                msg = "something went wrong"
                raise RuntimeError(msg)

        scheduler.add_task("flaky", flaky, interval=0.05, timeout=5)

        with patch("animetta.orchestration.graph.scheduler.logger") as mock_logger:
            await scheduler.start()
            await asyncio.sleep(0.4)
            await scheduler.stop()

            mock_logger.error.assert_called()
            assert "execution error" in str(mock_logger.error.call_args)

        metrics = scheduler.get_task_metrics("flaky")
        assert metrics is not None
        assert metrics.failure_count >= 1

    @pytest.mark.asyncio
    async def test_task_metrics_tracked(self, scheduler):
        """Successful executions update metrics counters."""
        barrier = asyncio.Event()

        async def single_shot():
            if not barrier.is_set():
                barrier.set()

        scheduler.add_task("metric", single_shot, interval=0.05, timeout=5)
        await scheduler.start()

        try:
            await asyncio.wait_for(barrier.wait(), timeout=5)
            await asyncio.sleep(0.15)  # Let metrics write
        finally:
            await scheduler.stop()

        metrics = scheduler.get_task_metrics("metric")
        assert metrics is not None
        assert metrics.total_runs >= 1
        assert metrics.success_count >= 1
        assert metrics.last_run is not None
        assert metrics.last_duration is not None


# ── Timeout protection ──────────────────────────────────────


class TestTimeout:
    """Task timeout protection."""

    @pytest.mark.asyncio
    async def test_task_times_out(self, scheduler):
        """A task that exceeds timeout is cancelled and failure tracked."""

        async def slow():
            await asyncio.sleep(999)  # longer than timeout

        # Use a very short interval so the task runs soon after start
        scheduler.add_task("slow", slow, interval=0.2, timeout=0.05)
        await scheduler.start()

        # Give enough time: initial_delay + timeout + buffer
        await asyncio.sleep(2.0)
        await scheduler.stop()

        metrics = scheduler.get_task_metrics("slow")
        assert metrics is not None
        assert metrics.failure_count >= 1, f"Expected >=1 failure, got {metrics.failure_count}"

    @pytest.mark.asyncio
    async def test_quick_task_no_timeout(self, scheduler):
        """A task that finishes within timeout succeeds."""
        done = asyncio.Event()

        async def fast():
            done.set()

        scheduler.add_task("fast", fast, interval=0.1, timeout=5)
        await scheduler.start()

        try:
            await asyncio.wait_for(done.wait(), timeout=5)
        finally:
            await scheduler.stop()

        metrics = scheduler.get_task_metrics("fast")
        assert metrics is not None
        assert metrics.failure_count == 0


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

    @pytest.mark.asyncio
    async def test_execution_time_measured(self, scheduler):
        """last_duration roughly matches actual execution time."""

        async def slow_enough():
            await asyncio.sleep(0.05)

        task = ScheduledTask(
            name="unit-duration",
            func=slow_enough,
            interval=1.0,
            timeout=5.0,
        )

        await scheduler._execute_with_timeout(task)

        assert task.metrics.last_duration is not None
        assert 0.03 <= task.metrics.last_duration <= 1.0  # allow leeway


# ── Edge cases ──────────────────────────────────────────────


class TestEdgeCases:
    """Scheduler edge cases."""

    @pytest.mark.asyncio
    async def test_no_tasks_start_stop_cleanly(self, scheduler):
        """Starting and stopping with zero tasks is clean."""
        await scheduler.start()
        assert scheduler._running
        await scheduler.stop()
        assert not scheduler._running

    @pytest.mark.asyncio
    async def test_remove_task_while_running(self, scheduler):
        """Can remove a task while the scheduler is running."""
        executed = asyncio.Event()

        async def single():
            executed.set()

        scheduler.add_task("live", single, interval=0.05, timeout=5)
        await scheduler.start()

        try:
            await asyncio.wait_for(executed.wait(), timeout=5)
        finally:
            scheduler.remove_task("live")
            await scheduler.stop()

        assert "live" not in scheduler._tasks

    @pytest.mark.asyncio
    async def test_re_add_task_after_removal(self, scheduler):
        """A task can be re-added after removal."""
        execution_count = 0
        barrier = asyncio.Event()

        async def fn():
            nonlocal execution_count
            execution_count += 1
            if execution_count >= 2:
                barrier.set()

        scheduler.add_task("re", fn, interval=0.05, timeout=5)
        await scheduler.start()

        # Let it run once, remove, re-add, let it run again
        try:
            await asyncio.sleep(0.2)
            scheduler.remove_task("re")
            await asyncio.sleep(0.1)
            scheduler.add_task("re", fn, interval=0.05, timeout=5)
            await asyncio.wait_for(barrier.wait(), timeout=5)
            assert execution_count >= 2
        finally:
            await scheduler.stop()
