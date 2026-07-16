"""Tests for the ingress message filter (core/message_filter.py).

The filter is the first line of defense against the "历史串台虫":
inspection pings and health probes must never reach the LLM pipeline
nor be persisted as conversation history.
"""

from __future__ import annotations

import pytest

from animetta.core.message_filter import (
    BLEED_MARKERS,
    is_inspection_probe,
    is_probe_message,
    should_skip_llm,
)

# ── should_skip_llm — textual probe detection ────────────────────────


class TestShouldSkipLlmTextual:
    """Text-only detection of probe-shaped messages."""

    @pytest.mark.parametrize(
        "text",
        [
            "[inspection] ping",
            "[inspection]healthcheck",
            "[health] ok",
            "[probe] 1+1",
            "[system] reload",
        ],
    )
    def test_probe_prefixes_skip(self, text: str):
        assert should_skip_llm(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "ping",
            "PING",
            "  Ping  ",
            "pong",
            "healthcheck",
            "health-check",
            "heartbeat",
        ],
    )
    def test_probe_tokens_skip(self, text: str):
        assert should_skip_llm(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "\n\t",
            None,  # type: ignore[arg-type] — defensive: empty/None treated as skip
        ],
    )
    def test_empty_or_whitespace_skips(self, text):
        # None would never be passed by callers (they extract data["text"]),
        # but the function should not crash on falsy input.
        if text is None:
            assert should_skip_llm(text or "") is True
        else:
            assert should_skip_llm(text) is True


class TestShouldSkipLlmRealChat:
    """Genuine user messages must NOT be skipped."""

    @pytest.mark.parametrize(
        "text",
        [
            "主播好",
            "ping 我一下呗",  # contains "ping" as substring, not bare
            "主播你又卡了",
            "讲个笑话",
            "pingpong 是不是运动",  # not exactly "ping" or "pong"
            "请问 healthcheck 怎么用",  # contains the word but not bare
            "我刚才发了一条 ping 你看到了吗",
        ],
    )
    def test_real_chat_not_skipped(self, text: str):
        assert should_skip_llm(text) is False


# ── is_inspection_probe — payload-flag detection ─────────────────────


class TestIsInspectionProbe:
    """Payload-level detection via explicit markers."""

    @pytest.mark.parametrize(
        "data",
        [
            {"text": "anything", "is_inspection": True},
            {"text": "x", "is_probe": True},
            {"text": "hello", "mode": "inspection"},
            {"is_inspection": True},  # even without text
        ],
    )
    def test_flagged_payloads_detected(self, data: dict):
        assert is_inspection_probe(data) is True

    @pytest.mark.parametrize(
        "data",
        [
            {"text": "主播好"},
            {"text": "[inspection] ping"},  # text probe, but no flag
            {"text": "x", "is_inspection": False},  # explicit False
            {"text": "x", "is_inspection": "true"},  # truthy string, not boolean True
            {"text": "x", "mode": "text"},
            {},  # empty payload
        ],
    )
    def test_unflagged_payloads_pass(self, data: dict):
        assert is_inspection_probe(data) is False

    def test_non_dict_payload_is_safe(self):
        """Non-dict input does not crash; treated as not-a-probe."""
        assert is_inspection_probe(None) is False  # type: ignore[arg-type]
        assert is_inspection_probe("not a dict") is False  # type: ignore[arg-type]
        assert is_inspection_probe(42) is False  # type: ignore[arg-type]


# ── is_probe_message — combined canonical entry point ────────────────


class TestIsProbeMessage:
    """The combined check used by ChatHandlers.on_text_input."""

    def test_payload_flag_short_circuits(self):
        """is_inspection=True drops the message regardless of text content."""
        assert is_probe_message({"text": "real-looking message", "is_inspection": True}) is True

    def test_text_probe_caught_when_no_flag(self):
        """Text-shaped probe is caught even without payload flag (backstop)."""
        assert is_probe_message({"text": "[inspection] ping"}) is True
        assert is_probe_message({"text": "ping"}) is True

    def test_genuine_chat_passes(self):
        assert is_probe_message({"text": "主播好"}) is False
        assert is_probe_message({"text": "讲个笑话", "from_name": "旅人A"}) is False

    def test_missing_text_key_safe(self):
        """Payload without 'text' key is handled gracefully.

        Note: an empty payload is conservatively treated as a skip — the
        existing ``if not text: return`` in ChatHandlers is a redundant
        backstop. The key contract here is "no crash, definite answer".
        """
        # Empty payload → skipped (defense in depth; nothing to send to LLM)
        assert is_probe_message({}) is True
        # No text but flagged → probe
        assert is_probe_message({"is_inspection": True}) is True


# ── BLEED_MARKERS — telemetry surface contract ───────────────────────


class TestBleedMarkers:
    """The bleed-marker list documents the bug signatures we watch for."""

    def test_markers_cover_documented_signatures(self):
        """The literal substrings from the bug report are present."""
        assert "tell me about 用户:" in BLEED_MARKERS
        assert "[inspection]" in BLEED_MARKERS
        assert "用户: " in BLEED_MARKERS
        assert "助手: " in BLEED_MARKERS

    def test_markers_are_strings(self):
        for m in BLEED_MARKERS:
            assert isinstance(m, str)
            assert len(m) > 0
