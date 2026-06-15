from __future__ import annotations

"""Tests for ModelLoadingManager — centralized model lifecycle."""

import asyncio
import contextlib

import pytest

from animetta.core.model_loading_manager import ModelLoadingManager, ModelLoadState, ModelSlot

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def manager():
    """Create a fresh ModelLoadingManager for each test."""
    return ModelLoadingManager()


# ── ModelLoadState enum ────────────────────────────────────────────


class TestModelLoadState:
    """Verify the enum values are what we expect."""

    def test_has_all_states(self):
        assert ModelLoadState.UNLOADED.value == "unloaded"
        assert ModelLoadState.LOADING.value == "loading"
        assert ModelLoadState.LOADED.value == "loaded"
        assert ModelLoadState.ERROR.value == "error"


# ── ModelSlot ──────────────────────────────────────────────────────


class TestModelSlot:
    """Unit tests for ModelSlot lifecycle."""

    def test_initial_state(self):
        slot = ModelSlot("test")
        assert slot.name == "test"
        assert slot.state == ModelLoadState.UNLOADED
        assert slot.instance is None
        assert slot.error is None
        assert not slot._event.is_set()

    def test_set_loaded(self):
        slot = ModelSlot("test")
        slot.set_loaded("instance_42")
        assert slot.state == ModelLoadState.LOADED
        assert slot.instance == "instance_42"
        assert slot._event.is_set()

    def test_set_error(self):
        slot = ModelSlot("test")
        exc = RuntimeError("boom")
        slot.set_error(exc)
        assert slot.state == ModelLoadState.ERROR
        assert slot.error is exc
        assert slot._event.is_set()

    @pytest.mark.asyncio
    async def test_wait_returns_instance(self):
        slot = ModelSlot("test")
        slot.set_loaded("instance_42")
        instance = await slot.wait()
        assert instance == "instance_42"

    @pytest.mark.asyncio
    async def test_wait_raises_error(self):
        slot = ModelSlot("test")
        exc = RuntimeError("boom")
        slot.set_error(exc)
        with pytest.raises(RuntimeError, match="boom"):
            await slot.wait()

    @pytest.mark.asyncio
    async def test_wait_timeout(self):
        slot = ModelSlot("test")
        # Never set the event — should time out.
        with pytest.raises(asyncio.TimeoutError):
            await slot.wait(timeout=0.01)


# ── ModelLoadingManager tests ──────────────────────────────────────


class TestRegisterAndGet:
    """Test register + get flow."""

    def test_register_sync_loader_loaded_immediately(self, manager):
        """Sync loader should be called during registration and return instance."""
        instance = manager.register("sync_model", lambda: "hello", service_name="Sync Service")
        assert instance == "hello"

        status = manager.get_status()
        assert status["sync_model"] == "loaded"

    @pytest.mark.asyncio
    async def test_register_async_loader_not_loaded(self, manager):
        """Async loader should NOT be called during registration."""
        manager.register(
            "async_model",
            lambda: "ignored",  # not actually co-routine
            service_name="Async Service",
        )
        # Since this isn't truly a coroutine function, it loads sync.
        # Let's test with a real async function:
        pass

    @pytest.mark.asyncio
    async def test_register_async_loader_stays_unloaded(self, manager):
        """An async loader function should leave the slot UNLOADED."""
        async def async_loader():
            return "async_result"

        result = manager.register("async_model", async_loader)
        assert result is None  # not loaded eagerly
        assert manager.get_status()["async_model"] == "unloaded"


class TestWarmupAndAwait:
    """Test warmup + get awaiting."""

    @pytest.mark.asyncio
    async def test_warmup_and_await(self, manager):
        """Register async slow loader, warmup, get should await and return."""
        call_order = []

        async def slow_loader():
            call_order.append("start")
            await asyncio.sleep(0.05)
            call_order.append("done")
            return "slow_result"

        manager.register("slow_model", slow_loader, service_name="Slow Service")

        status_before = manager.get_status()
        assert status_before["slow_model"] == "unloaded"

        await manager.warmup()

        status_after = manager.get_status()
        assert status_after["slow_model"] == "loaded"

        instance = await manager.get("slow_model")
        assert instance == "slow_result"
        assert call_order == ["start", "done"]

    @pytest.mark.asyncio
    async def test_get_triggers_lazy_load(self, manager):
        """First get() on an UNLOADED async model should load it."""
        async def lazy_loader():
            await asyncio.sleep(0.02)
            return "lazy_result"

        manager.register("lazy_model", lazy_loader)
        instance = await manager.get("lazy_model")
        assert instance == "lazy_result"
        assert manager.get_status()["lazy_model"] == "loaded"

    @pytest.mark.asyncio
    async def test_get_already_loaded_returns_immediately(self, manager):
        """get() for a loaded model should return without calling loader again."""
        call_count = 0

        def sync_loader():
            nonlocal call_count
            call_count += 1
            return "instant"

        manager.register("instant_model", sync_loader)
        assert call_count == 1

        instance = await manager.get("instant_model")
        assert instance == "instant"
        assert call_count == 1  # loader called only once


class TestGetStatus:
    """Test get_status() returns correct dict."""

    def test_get_status_format(self, manager):
        """Verify status dict format."""
        manager.register("a", lambda: 1)
        manager.register("b", lambda: 2)
        status = manager.get_status()
        assert isinstance(status, dict)
        assert status["a"] == "loaded"
        assert status["b"] == "loaded"

    def test_get_status_empty(self):
        """Empty manager should return empty dict."""
        mgr = ModelLoadingManager()
        assert mgr.get_status() == {}


class TestWarmupConcurrent:
    """Test concurrent warmup of multiple services."""

    @pytest.mark.asyncio
    async def test_two_services_concurrent(self, manager):
        """Two services with different speeds — both should complete."""
        timeline = []

        async def fast_loader():
            timeline.append("fast_start")
            await asyncio.sleep(0.03)
            timeline.append("fast_done")
            return "fast"

        async def slow_loader():
            timeline.append("slow_start")
            await asyncio.sleep(0.06)
            timeline.append("slow_done")
            return "slow"

        manager.register("fast", fast_loader)
        manager.register("slow", slow_loader)

        await manager.warmup()

        status = manager.get_status()
        assert status["fast"] == "loaded"
        assert status["slow"] == "loaded"

        assert await manager.get("fast") == "fast"
        assert await manager.get("slow") == "slow"

        # Both started before either finished (true concurrency)
        fast_start_idx = timeline.index("fast_start")
        slow_start_idx = timeline.index("slow_start")
        assert max(fast_start_idx, slow_start_idx) < len(timeline) - 2

    @pytest.mark.asyncio
    async def test_mixed_sync_and_async(self, manager):
        """Mixed sync and async services — sync already loaded, async loaded during warmup."""

        async def async_loader():
            await asyncio.sleep(0.02)
            return "async_value"

        manager.register("sync_model", lambda: "sync_value")
        manager.register("async_model", async_loader)

        status_before = manager.get_status()
        assert status_before["sync_model"] == "loaded"
        assert status_before["async_model"] == "unloaded"

        await manager.warmup()

        status_after = manager.get_status()
        assert status_after["sync_model"] == "loaded"
        assert status_after["async_model"] == "loaded"

        assert await manager.get("sync_model") == "sync_value"
        assert await manager.get("async_model") == "async_value"


class TestLoadError:
    """Test error handling during loading."""

    @pytest.mark.asyncio
    async def test_sync_load_error_propagates(self, manager):
        """Sync loader that raises should propagate immediately."""
        def failing_loader():
            raise RuntimeError("sync fail")

        with pytest.raises(RuntimeError, match="sync fail"):
            manager.register("failing", failing_loader)

        status = manager.get_status()
        assert status["failing"] == "error"

    @pytest.mark.asyncio
    async def test_async_load_error_during_warmup(self, manager):
        """Async loader that fails should record error without crashing warmup."""
        async def failing_loader():
            raise ValueError("async fail")

        manager.register("failing_async", failing_loader)
        # Warmup should NOT raise — the error is captured.
        await manager.warmup()

        status = manager.get_status()
        assert status["failing_async"] == "error"

        with pytest.raises(ValueError, match="async fail"):
            await manager.get("failing_async")

    @pytest.mark.asyncio
    async def test_async_load_error_during_get(self, manager):
        """Lazy load via get() should propagate the loader error."""
        async def failing_loader():
            raise RuntimeError("lazy fail")

        manager.register("lazy_fail", failing_loader)

        with pytest.raises(RuntimeError, match="lazy fail"):
            await manager.get("lazy_fail")

        assert manager.get_status()["lazy_fail"] == "error"

    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_others(self, manager):
        """One failing loader should not prevent others from loading."""
        async def good_loader():
            await asyncio.sleep(0.02)
            return "good_result"

        async def bad_loader():
            raise RuntimeError("bad")

        manager.register("good", good_loader)
        manager.register("bad", bad_loader)

        await manager.warmup()

        status = manager.get_status()
        assert status["good"] == "loaded"
        assert status["bad"] == "error"

        assert await manager.get("good") == "good_result"
        with pytest.raises(RuntimeError, match="bad"):
            await manager.get("bad")


class TestGetUnregistered:
    """Test error handling for unregistered names."""

    @pytest.mark.asyncio
    async def test_get_unregistered_raises_keyerror(self, manager):
        """get() for an unregistered name should raise KeyError."""
        with pytest.raises(KeyError, match="not_registered"):
            await manager.get("not_registered")


class TestWaitAll:
    """Test wait_all behavior."""

    @pytest.mark.asyncio
    async def test_wait_all_all_loaded(self, manager):
        """wait_all should return True when all models load successfully."""
        manager.register("a", lambda: 1)
        manager.register("b", lambda: 2)
        result = await manager.wait_all()
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_all_with_errors(self, manager):
        """wait_all should return False when some models have errors."""
        manager.register("good", lambda: 1)

        def fail():
            raise RuntimeError("fail")

        with contextlib.suppress(RuntimeError):
            manager.register("bad", fail)  # sync error is expected

        result = await manager.wait_all()
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_all_empty_manager(self):
        """wait_all on empty manager should return True."""
        mgr = ModelLoadingManager()
        result = await mgr.wait_all()
        assert result is True


class TestSocketIOIntegration:
    """Test Socket.IO event emission during loading."""

    def test_status_emitted_on_sync_load(self):
        """model_status event is emitted when sync loader succeeds."""
        from unittest.mock import MagicMock

        mock_sio = MagicMock()
        mgr = ModelLoadingManager(socketio=mock_sio)
        mgr.register("test_model", lambda: "value")

        mock_sio.emit.assert_called()
        call_args = mock_sio.emit.call_args_list[0][0]
        assert call_args[0] == "system:model_status"
        assert call_args[1]["name"] == "test_model"
        assert call_args[1]["status"] == "loaded"

    def test_status_emitted_on_sync_error(self):
        """model_status event is emitted when sync loader fails."""
        from unittest.mock import MagicMock

        mock_sio = MagicMock()
        mgr = ModelLoadingManager(socketio=mock_sio)

        def fail():
            raise RuntimeError("boom")

        with contextlib.suppress(RuntimeError):
            mgr.register("bad_model", fail)

        mock_sio.emit.assert_called()
        call_args = mock_sio.emit.call_args_list[0][0]
        assert call_args[0] == "system:model_status"
        assert call_args[1]["name"] == "bad_model"
        assert call_args[1]["status"] == "error"
        assert "boom" in call_args[1]["error"]

    def test_no_emit_without_socketio(self):
        """When socketio is None, emit is never called."""
        mgr = ModelLoadingManager()  # no socketio
        mgr.register("test_model", lambda: "value")
        # Should work without any issue
        assert mgr.get_status()["test_model"] == "loaded"

    @pytest.mark.asyncio
    async def test_status_emitted_on_async_load(self):
        """model_status events are emitted during async warmup."""
        from unittest.mock import MagicMock

        mock_sio = MagicMock()
        mgr = ModelLoadingManager(socketio=mock_sio)

        async def async_loader():
            await asyncio.sleep(0.02)
            return "async_value"

        mgr.register("async_model", async_loader)
        await mgr.warmup()

        # Should have loading + loaded emissions
        emitted_statuses = [
            call[0][1]["status"]
            for call in mock_sio.emit.call_args_list
        ]
        assert "loading" in emitted_statuses
        assert "loaded" in emitted_statuses

    @pytest.mark.asyncio
    async def test_socketio_failure_does_not_crash_loader(self):
        """A failing Socket.IO emit should not prevent model loading."""
        from unittest.mock import MagicMock

        mock_sio = MagicMock()
        mock_sio.emit.side_effect = RuntimeError("socketio down")

        mgr = ModelLoadingManager(socketio=mock_sio)

        async def async_loader():
            await asyncio.sleep(0.02)
            return "value"

        mgr.register("resilient", async_loader)
        # Should not raise
        await mgr.warmup()

        assert mgr.get_status()["resilient"] == "loaded"
        assert await mgr.get("resilient") == "value"
