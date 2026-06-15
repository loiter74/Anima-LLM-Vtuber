"""
Feishu Notifier Plugin.

Converts Alertmanager alerts to Feishu interactive card format
and sends via webhook. Supports HMAC-SHA256 signature verification.
"""

import hashlib
import hmac
import logging
import os
import time
from base64 import b64encode

import httpx

from animetta.notifier.base import NotifierBase, register_notifier

logger = logging.getLogger(__name__)

SEVERITY_TEMPLATES = {
    "critical": "red",
    "warning": "yellow",
    "info": "blue",
}
RESOLVED_TEMPLATE = "green"


def _generate_sign(secret: str) -> tuple[str, str]:
    """Generate HMAC-SHA256 signature for Feishu webhook."""
    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    sign = b64encode(hmac_code.digest()).decode("utf-8")
    return timestamp, sign


def _build_card(alert: dict, status: str) -> dict:
    """Build a Feishu interactive card for a single alert."""
    severity = alert.get("severity", "warning")
    template = RESOLVED_TEMPLATE if status == "resolved" else SEVERITY_TEMPLATES.get(severity, "yellow")
    prefix = "✅ [RESOLVED]" if status == "resolved" else "🚨 [FIRING]"

    description = alert.get("summary", alert.get("description", ""))
    if len(description) > 2000:
        description = description[:1997] + "..."

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"{prefix} {alert['name']}"},
                "template": template,
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**Severity:** {severity}\n"
                            f"**Status:** {status}\n"
                            f"**Summary:** {description}"
                        ),
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"Starts at: {alert.get('starts_at', 'N/A')}"}],
                },
            ],
        },
    }


@register_notifier("feishu")
class FeishuNotifier(NotifierBase):
    """Send alert notifications to a Feishu (Lark) group via webhook."""

    def __init__(self):
        self.webhook_url = os.getenv("NOTIFIER_FEISHU_WEBHOOK_URL", "")
        self.sign_secret = os.getenv("NOTIFIER_FEISHU_SIGN_SECRET", "")

    async def send(self, alerts: list[dict], status: str) -> bool:
        if not self.webhook_url:
            logger.warning("Feishu webhook URL not configured")
            return False

        for alert in alerts:
            payload = _build_card(alert, status)

            # Attach signature if configured
            if self.sign_secret:
                ts, sig = _generate_sign(self.sign_secret)
                payload["timestamp"] = ts
                payload["sign"] = sig

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                if not resp.is_success:
                    logger.warning(
                        "Feishu webhook returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return False

        return True
