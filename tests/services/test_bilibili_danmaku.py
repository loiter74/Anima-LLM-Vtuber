from __future__ import annotations

"""Tests for BilibiliDanmakuService — connect/disconnect/reconnect lifecycle.

Uses @patch + sys.modules manipulation to mock bilibili_api at module level.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.services.bilibili import DanmakuMessage, DanmakuReply, DanmakuService

# ── Mock bilibili_api before importing the service ────────────────────
mock_bilibili_api = MagicMock()
mock_live = MagicMock()
mock_credential = MagicMock()

mock_bilibili_api.live = mock_live
mock_bilibili_api.Credential = mock_credential

# Patch sys.modules so any 'from bilibili_api import ...' resolves to our mock
sys.modules["bilibili_api"] = mock_bilibili_api
sys.modules["bilibili_api.live"] = mock_live


@pytest.fixture(autouse=True)
def _reset_mocks():
    """Reset all mock state before each test."""
    mock_live.LiveDanmaku.reset_mock()
    mock_credential.reset_mock()
    yield
    # Clean up
    for key in list(sys.modules.keys()):
        if key.startswith("bilibili_api"):
            pass  # keep our mocks in place


@pytest.fixture
def service():
    """A BilibiliDanmakuService instance with a mocked event loop.

    We override _run_event_loop to avoid actually starting threads.
    """

    svc = DanmakuService(room_id=12345, sessdata="test_sessdata")
    return svc


class TestBilibiliDanmakuDataclasses:
    """Dataclass tests (no mocking needed)."""

    def test_danmaku_message_creation(self):

        msg = DanmakuMessage(text="hello", user_name="user1", user_id=1001)
        assert msg.text == "hello"
        assert msg.user_name == "user1"
        assert msg.user_id == 1001
        assert msg.timestamp > 0

    def test_danmaku_message_to_dict(self):

        msg = DanmakuMessage(text="hello", user_name="user1", user_id=1001)
        d = msg.to_dict()
        assert d["text"] == "hello"
        assert d["user_name"] == "user1"
        assert d["user_id"] == 1001

    def test_danmaku_reply_creation(self):

        reply = DanmakuReply(
            danmaku_text="hello",
            reply_text="hi there",
            user_name="user1",
        )
        assert reply.danmaku_text == "hello"
        assert reply.reply_text == "hi there"
        assert reply.character_name == "AI"

    def test_danmaku_reply_to_dict(self):

        reply = DanmakuReply(
            danmaku_text="hello",
            reply_text="hi",
            user_name="user1",
            character_name="Anima",
        )
        d = reply.to_dict()
        assert d["character_name"] == "Anima"


class TestBilibiliDanmakuService:
    """Suite for BilibiliDanmakuService lifecycle."""

    # ── Initial state ────────────────────────────────────────────────

    def test_initial_state(self, service):
        """Service starts not connected, not running."""
        assert service._running is False
        assert service._connected is False
        assert service._thread is None
        assert service._on_danmaku is None
        assert service.room_id == 12345
        assert service.sessdata == "test_sessdata"

    # ── Callback registration ────────────────────────────────────────

    def test_set_callback(self, service):
        callback = MagicMock()
        service.set_callback(callback)
        assert service._on_danmaku is callback

    def test_set_status_callback(self, service):
        callback = MagicMock()
        service.set_status_callback(callback)
        assert service._on_status_change is callback

    # ── is_connected property ────────────────────────────────────────

    def test_is_connected_property(self, service):
        assert service.is_connected is False
        service._connected = True
        assert service.is_connected is True

    # ── start / stop lifecycle ───────────────────────────────────────

    def test_start_creates_thread(self, service):
        """start() should create and start a daemon thread."""
        with patch.object(service, "_run_event_loop"):
            service.start()
            assert service._running is True
            assert service._thread is not None
            assert service._thread.daemon is True
            assert "bilibili-danmaku" in service._thread.name
            service.stop()

    def test_start_idempotent(self, service):
        """Calling start() twice should not create a second thread."""
        with patch.object(service, "_run_event_loop"):
            service.start()
            thread_id = id(service._thread)
            service.start()  # second call — warning, no-op
            assert id(service._thread) == thread_id
            service.stop()

    def test_stop_without_start(self, service):
        """stop() when not running should be safe."""
        service.stop()  # should not raise
        assert service._connected is False

    def test_stop_sets_connected_false(self, service):
        """After stop, _connected is False."""
        with patch.object(service, "_run_event_loop"):
            service.start()
            service._connected = True
            service.stop()
            assert service._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_cleans_monitor(self, service):
        """_disconnect should set _monitor to None."""
        mock_monitor = MagicMock()
        mock_monitor.disconnect = AsyncMock()
        service._monitor = mock_monitor
        await service._disconnect()
        mock_monitor.disconnect.assert_awaited_once()
        assert service._monitor is None

    @pytest.mark.asyncio
    async def test_connected_status_waits_for_verification_event(self, service):
        """Connection truth is published only after Bilibili verifies the handshake."""
        handlers = {}
        monitor = MagicMock()

        def register(event_name):
            def decorator(callback):
                handlers[event_name] = callback
                return callback

            return decorator

        monitor.on.side_effect = register
        monitor.disconnect = AsyncMock()
        status_callback = MagicMock()
        service.set_status_callback(status_callback)

        async def connect_and_verify():
            status_callback.assert_not_called()
            await handlers["VERIFICATION_SUCCESSFUL"]({})

        monitor.connect = AsyncMock(side_effect=connect_and_verify)
        mock_live.LiveDanmaku.return_value = monitor

        await service._connect_and_listen()

        status_callback.assert_any_call(True, "Connected")

    # ── _notify_status ───────────────────────────────────────────────

    def test_notify_status_with_callback(self, service):
        status_cb = MagicMock()
        service.set_status_callback(status_cb)
        service._notify_status(True, "Connected")
        status_cb.assert_called_once_with(True, "Connected")
        assert service._connected is True

    def test_notify_status_no_callback(self, service):
        """Should not crash when no callback is set."""
        service._notify_status(False, "Disconnected")
        assert service._connected is False

    # ── Reconnection ─────────────────────────────────────────────────

    def test_reconnect_delay_starts_at_1(self, service):
        assert service._reconnect_delay == 1.0

    @pytest.mark.asyncio
    async def test_reconnect_backoff(self, service):
        """_run should double reconnect_delay on each failure up to 60s."""
        service._running = True

        # Mock _connect_and_listen to always fail
        with patch.object(service, "_connect_and_listen", side_effect=ConnectionError("fail")):
            # Set max_retries to 2 so it doesn't loop forever
            service.max_retries = 2
            with patch.object(service, "_notify_status"), patch("asyncio.sleep", AsyncMock()):
                await service._run()

        # After 2 retries, delay should be: 1.0 * 2 * 2 = 4.0
        assert service._reconnect_delay == 4.0

    @pytest.mark.asyncio
    async def test_reconnect_resets_on_success(self, service):
        """After a successful connection, reconnect_delay resets to 1.0."""
        service._running = True
        service._reconnect_delay = 8.0

        async def connect_once_then_stop():
            service._running = False

        with (
            patch.object(
                service,
                "_connect_and_listen",
                AsyncMock(side_effect=connect_once_then_stop),
            ),
            patch("asyncio.sleep", AsyncMock()),
        ):
            await service._run()

        assert service._reconnect_delay == 1.0

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, service):
        """When max_retries is reached, _run should stop and notify."""
        service._running = True
        service.max_retries = 1

        with (
            patch.object(service, "_connect_and_listen", side_effect=ConnectionError("fail")),
            patch.object(service, "_notify_status") as mock_notify,
            patch("asyncio.sleep", AsyncMock()),
        ):
            await service._run()

        # Should have notified about max retries
        mock_notify.assert_any_call(False, "Max retries reached")

    @pytest.mark.asyncio
    async def test_missing_dependency_fails_without_retrying(self, service):
        service._running = True
        service.max_retries = 5

        with (
            patch.object(
                service,
                "_connect_and_listen",
                AsyncMock(side_effect=ImportError("credential=secret")),
            ) as connect,
            patch.object(service, "_notify_status") as notify,
        ):
            await service._run()

        connect.assert_awaited_once()
        notify.assert_called_once_with(False, "Dependency unavailable")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (type("CredentialNoSessdataException", (Exception,), {})(), "Invalid credentials"),
            (type("ResponseError", (Exception,), {"code": -101})(), "Invalid credentials"),
            (type("InvalidRoomException", (Exception,), {})(), "Invalid room"),
            (type("ResponseError", (Exception,), {"code": -404})(), "Invalid room"),
        ],
    )
    async def test_terminal_connection_errors_do_not_retry(self, service, error, status):
        service._running = True

        with (
            patch.object(
                service,
                "_connect_and_listen",
                AsyncMock(side_effect=error),
            ) as connect,
            patch.object(service, "_notify_status") as notify,
        ):
            await service._run()

        connect.assert_awaited_once()
        notify.assert_called_once_with(False, status)
