from __future__ import annotations

"""Tests for Live2DHandlers — desktop chat ingress filtering.

Covers the ``desktop.chat_message`` probe-containment guard (audit P0-1) and
the bad-payload path (audit P1-5). The guard mirrors
``ChatHandlers.on_text_event``'s ``is_probe_message`` check so inspection /
health probes cannot reach the LLM through the desktop transport.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.server.handlers.live2d_handlers import Live2DHandlers


@pytest.fixture
def handler():
    """Fresh Live2DHandlers with mocked sio and admin (BaseSocketHandler)."""
    sio = MagicMock()
    sio.emit = AsyncMock()
    admin = MagicMock()
    admin._get_or_create_orchestrator = AsyncMock()
    return Live2DHandlers(sio, MagicMock(), admin), sio, admin


# ── Probe containment (P0-1) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inspection_flag_probe_is_dropped(handler) -> None:
    """A payload self-flagged as inspection never reaches the orchestrator."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message(
        "sid", {"text": "hello", "is_inspection": True}
    )

    admin._get_or_create_orchestrator.assert_not_awaited()
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_is_probe_flag_alias_is_dropped(handler) -> None:
    """The ``is_probe`` alias is also honored."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message("sid", {"text": "hi", "is_probe": True})

    admin._get_or_create_orchestrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_mode_inspection_is_dropped(handler) -> None:
    """``mode == "inspection"`` payloads are dropped."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message(
        "sid", {"text": "hi", "mode": "inspection"}
    )

    admin._get_or_create_orchestrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_probe_token_ping_is_dropped(handler) -> None:
    """A bare ``"ping"`` is a health probe and must not reach the LLM."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message("sid", {"text": "ping"})

    admin._get_or_create_orchestrator.assert_not_awaited()
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_inspection_prefix_text_is_dropped(handler) -> None:
    """The ``[inspection]`` prefix marks a probe even without the flag."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message("sid", {"text": "[inspection] secret"})

    admin._get_or_create_orchestrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_text_is_dropped(handler) -> None:
    """Empty / whitespace-only text is treated as a probe and dropped."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message("sid", {"text": "   "})

    admin._get_or_create_orchestrator.assert_not_awaited()


# ── Bad-payload robustness (P1-5) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_text_key_does_not_raise(handler) -> None:
    """A payload without a ``text`` key must not raise."""
    live2d, sio, admin = handler

    # No "text" key → empty string → probe-dropped before orchestrator.
    await live2d.on_desktop_chat_message("sid", {"unrelated": "value"})

    admin._get_or_create_orchestrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_dict_payload_does_not_raise(handler) -> None:
    """A non-dict payload is handled defensively without raising."""
    live2d, sio, admin = handler

    # is_probe_message returns False for non-dict (data.get would fail inside
    # the filter, but the filter guards isinstance(data, dict)); the handler
    # then reads text="" which is probe-dropped.
    await live2d.on_desktop_chat_message("sid", None)  # type: ignore[arg-type]

    admin._get_or_create_orchestrator.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_value_is_not_a_string_does_not_crash_filter(handler) -> None:
    """A non-string ``text`` value is handled gracefully (dropped)."""
    live2d, sio, admin = handler

    await live2d.on_desktop_chat_message("sid", {"text": 12345})

    admin._get_or_create_orchestrator.assert_not_awaited()


# ── Normal path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_normal_message_dispatches_to_orchestrator(handler) -> None:
    """A genuine chat message reaches orchestrator.process_text exactly once."""
    live2d, _, admin = handler
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(return_value={})
    admin._get_or_create_orchestrator.return_value = orchestrator

    await live2d.on_desktop_chat_message("sid", {"text": "hello there"})

    admin._get_or_create_orchestrator.assert_awaited_once_with("sid")
    orchestrator.process_text.assert_awaited_once_with(
        text="hello there",
        user_id="user",
        user_name="User",
        channel_id="sid",
    )


@pytest.mark.asyncio
async def test_orchestrator_error_emits_system_error(handler) -> None:
    """If the orchestrator raises, a system:error event is emitted to the sid."""
    live2d, sio, admin = handler
    admin._get_or_create_orchestrator.side_effect = RuntimeError("boom")

    await live2d.on_desktop_chat_message("sid", {"text": "hello"})

    sio.emit.assert_awaited_once()
    args, kwargs = sio.emit.call_args
    # Event name is the system:error catalog name; payload carries the message.
    assert kwargs.get("to") == "sid"
    payload = args[1] if len(args) > 1 else kwargs.get("data")
    assert "boom" in str(payload)
