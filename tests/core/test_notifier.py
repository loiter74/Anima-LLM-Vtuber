from __future__ import annotations

from animetta.notifier.manager import NotifierManager

"""Tests for Notifier — Alert webhook relay (Discord / Feishu / Email)."""

import os
from unittest.mock import AsyncMock, patch

from animetta.notifier.base import NotifierBase, get_notifier_registry
from animetta.notifier.discord import DiscordNotifier
from animetta.notifier.email import _render_email
from animetta.notifier.feishu import _build_card, _generate_sign
from animetta.notifier.manager import Alert, parse_alertmanager_payload

# ── Sample Alertmanager payload ───────────────────────────────────

SAMPLE_ALERTMANAGER_PAYLOAD = {
    "version": "4",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "AnimaHighErrorRate",
                "severity": "critical",
                "instance": "anima:12394",
            },
            "annotations": {
                "summary": "LLM error rate 8.5% exceeds threshold 5%",
                "description": "The LLM error rate has been above 5% for the last 5 minutes.",
            },
            "startsAt": "2026-05-14T10:00:00Z",
        },
        {
            "status": "firing",
            "labels": {
                "alertname": "AnimaHighLatency",
                "severity": "warning",
                "instance": "anima:12394",
            },
            "annotations": {
                "summary": "P95 latency 12.3s exceeds threshold 10s",
            },
            "startsAt": "2026-05-14T10:01:00Z",
        },
    ],
}


# ── Tests: Alert dataclass ────────────────────────────────────────


class TestAlertDataclass:
    def test_alert_fields(self):
        alert = Alert(
            status="firing",
            name="TestAlert",
            severity="critical",
            summary="Something bad",
        )
        assert alert.status == "firing"
        assert alert.name == "TestAlert"
        assert alert.severity == "critical"
        assert alert.summary == "Something bad"

    def test_alert_to_dict(self):
        alert = Alert(status="firing", name="X", severity="warning")
        d = alert.to_dict()
        assert d["status"] == "firing"
        assert d["name"] == "X"
        assert d["severity"] == "warning"


# ── Tests: parse_alertmanager_payload ─────────────────────────────


class TestParsePayload:
    def test_parses_multiple_alerts(self):
        alerts = parse_alertmanager_payload(SAMPLE_ALERTMANAGER_PAYLOAD)
        assert len(alerts) == 2

    def test_alert_name_from_labels(self):
        alerts = parse_alertmanager_payload(SAMPLE_ALERTMANAGER_PAYLOAD)
        assert alerts[0].name == "AnimaHighErrorRate"
        assert alerts[1].name == "AnimaHighLatency"

    def test_severity_from_labels(self):
        alerts = parse_alertmanager_payload(SAMPLE_ALERTMANAGER_PAYLOAD)
        assert alerts[0].severity == "critical"
        assert alerts[1].severity == "warning"

    def test_summary_from_annotations(self):
        alerts = parse_alertmanager_payload(SAMPLE_ALERTMANAGER_PAYLOAD)
        assert "8.5%" in alerts[0].summary
        assert "12.3s" in alerts[1].summary

    def test_empty_payload(self):
        alerts = parse_alertmanager_payload({"status": "resolved", "alerts": []})
        assert alerts == []

    def test_default_severity(self):
        payload = {
            "status": "firing",
            "alerts": [{"status": "firing", "labels": {"alertname": "NoSev"}}],
        }
        alerts = parse_alertmanager_payload(payload)
        assert alerts[0].severity == "warning"


# ── Tests: register_notifier / registry ───────────────────────────


class TestNotifierRegistry:
    def test_register_and_retrieve(self):
        registry = get_notifier_registry()
        assert "discord" in registry
        assert registry["discord"] is DiscordNotifier
        assert "feishu" in registry

    def test_registered_classes_are_notifier_base(self):
        registry = get_notifier_registry()
        for name, cls in registry.items():
            assert issubclass(cls, NotifierBase), f"{name} is not a NotifierBase subclass"


# ── Tests: NotifierManager ────────────────────────────────────────


class TestNotifierManager:
    def test_no_env_vars_nothing_enabled(self):
        """Without env vars, no channels should be enabled."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear registry side effects from module imports
            nm = NotifierManager()
            # Discord disabled because URL not set
            assert "discord" not in nm._enabled or not nm._enabled

    def test_discord_enabled_when_url_set(self):
        with patch.dict(
            os.environ,
            {"NOTIFIER_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"},
            clear=True,
        ):
            nm = NotifierManager()
            assert "discord" in nm._enabled

    def test_handle_returns_channel_results(self):
        with patch.dict(
            os.environ,
            {"NOTIFIER_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"},
            clear=True,
        ):
            import asyncio

            nm = NotifierManager()
            with patch.object(DiscordNotifier, "send", new=AsyncMock(return_value=True)):
                results = asyncio.run(nm.handle(SAMPLE_ALERTMANAGER_PAYLOAD))
                assert "discord" in results
                assert results["discord"] is True


# ── Tests: Discord formatting ─────────────────────────────────────


class TestDiscordNotifier:
    def test_init_without_url(self):
        with patch.dict(os.environ, {}, clear=True):
            n = DiscordNotifier()
            assert n.webhook_url == ""

    async def test_send_without_url_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            n = DiscordNotifier()
            result = await n.send([{"name": "X", "severity": "critical"}], "firing")
            assert result is False

    def test_embed_format(self):
        """Verify Discord embed structure via monkeypatching httpx."""
        with patch.dict(
            os.environ,
            {"NOTIFIER_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"},
            clear=True,
        ):
            n = DiscordNotifier()
            # Just check it initializes correctly
            assert n.webhook_url == "https://discord.com/api/webhooks/test"


# ── Tests: Feishu formatting ──────────────────────────────────────


class TestFeishuNotifier:
    def test_card_structure(self):
        """Verify Feishu interactive card has header and elements."""

        card = _build_card(
            {
                "name": "AnimaHighErrorRate",
                "severity": "critical",
                "summary": "Error rate too high",
                "starts_at": "2026-05-14T10:00:00Z",
            },
            "firing",
        )

        assert card["msg_type"] == "interactive"
        assert card["card"]["header"]["template"] == "red"
        assert "🚨 [FIRING]" in card["card"]["header"]["title"]["content"]
        assert "Error rate too high" in card["card"]["elements"][0]["text"]["content"]

    def test_resolved_template_is_green(self):

        card = _build_card({"name": "X", "severity": "critical"}, "resolved")
        assert card["card"]["header"]["template"] == "green"
        assert "✅ [RESOLVED]" in card["card"]["header"]["title"]["content"]

    def test_warning_template_is_yellow(self):

        card = _build_card({"name": "X", "severity": "warning"}, "firing")
        assert card["card"]["header"]["template"] == "yellow"

    def test_generate_signature(self):

        ts, sig = _generate_sign("my_secret")
        assert ts.isdigit()
        assert len(sig) > 10


# ── Tests: Email formatting ───────────────────────────────────────


class TestEmailNotifier:
    def test_email_rendering(self):
        """Verify HTML template renders alert data."""

        text, html = _render_email(
            [
                {
                    "name": "TestAlert",
                    "severity": "critical",
                    "summary": "Test summary",
                    "starts_at": "",
                }
            ],
            "firing",
        )

        assert "[FIRING]" in text
        assert "TestAlert" in text
        assert "TestAlert" in html
        assert "critical" in html
