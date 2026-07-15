"""
Discord Notifier Plugin.

Converts Alertmanager alerts to Discord embed format
and sends via webhook.
"""

import logging
import os
from typing import Any

import httpx

from animetta.notifier.base import NotifierBase, register_notifier

logger = logging.getLogger(__name__)

SEVERITY_COLORS = {
    "critical": 0xE74C3C,  # Red
    "warning": 0xF1C40F,  # Yellow
    "info": 0x3498DB,  # Blue
}
RESOLVED_COLOR = 0x2ECC71  # Green


@register_notifier("discord")
class DiscordNotifier(NotifierBase):
    """Send alert notifications to a Discord channel via webhook."""

    def __init__(self):
        self.webhook_url = os.getenv("NOTIFIER_DISCORD_WEBHOOK_URL", "")

    async def send(self, alerts: list[dict], status: str) -> bool:
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured")
            return False

        embeds = []
        for alert in alerts:
            severity = alert.get("severity", "warning")
            color = (
                RESOLVED_COLOR
                if status == "resolved"
                else SEVERITY_COLORS.get(severity, SEVERITY_COLORS["warning"])
            )

            prefix = "✅ [RESOLVED]" if status == "resolved" else "🚨 [FIRING]"

            embeds.append(
                {
                    "title": f"{prefix} {alert['name']}",
                    "description": alert.get("summary", alert.get("description", "")),
                    "color": color,
                    "fields": [
                        {"name": "Severity", "value": severity, "inline": True},
                        {"name": "Status", "value": status, "inline": True},
                    ],
                    "timestamp": alert.get("starts_at", ""),
                }
            )

        payload: dict[str, Any] = {"embeds": embeds}
        if len(alerts) == 1:
            payload["content"] = f"**{alerts[0]['name']}** — {alerts[0].get('summary', '')}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self.webhook_url, json=payload)
            if resp.status_code == 204:
                return True
            if resp.status_code == 429:
                logger.warning("Discord rate limited (429)")
                return False
            logger.warning("Discord webhook returned %d: %s", resp.status_code, resp.text[:200])
            return resp.is_success
