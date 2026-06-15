"""
Email Notifier Plugin.

Sends alert notifications via SMTP with text + HTML (multipart/alternative).
Uses Jinja2 for HTML template rendering and smtplib via asyncio.to_thread().
"""

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from animetta.notifier.base import NotifierBase, register_notifier

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _render_email(alerts: list[dict], status: str) -> tuple[str, str]:
    """Render text and HTML email bodies."""
    template = _JINJA_ENV.get_template("email_alert.html")
    html = template.render(alerts=alerts, status=status)

    # Plain text fallback
    lines = [f"[{status.upper()}] Anima Alert", "=" * 40, ""]
    for a in alerts:
        lines.append(f"{a['name']} ({a.get('severity', 'warning')})")
        lines.append(f"  {a.get('summary', a.get('description', ''))}")
        lines.append(f"  Started: {a.get('starts_at', 'N/A')}")
        lines.append("")
    text = "\n".join(lines)

    return text, html


@register_notifier("email")
class EmailNotifier(NotifierBase):
    """Send alert notifications via SMTP email."""

    def __init__(self):
        self.smtp_host = os.getenv("NOTIFIER_SMTP_HOST", "")
        self.smtp_port = int(os.getenv("NOTIFIER_SMTP_PORT", "587"))
        self.smtp_user = os.getenv("NOTIFIER_SMTP_USER", "")
        self.smtp_password = os.getenv("NOTIFIER_SMTP_PASSWORD", "")
        self.from_addr = os.getenv("NOTIFIER_EMAIL_FROM", "alerts@anima.local")
        self.to_addrs = [
            addr.strip()
            for addr in os.getenv("NOTIFIER_EMAIL_TO", "").split(",")
            if addr.strip()
        ]

    async def send(self, alerts: list[dict], status: str) -> bool:
        if not self.to_addrs or not self.smtp_host:
            logger.warning("Email not configured (missing SMTP host or recipients)")
            return False

        text_body, html_body = _render_email(alerts, status)

        prefix = "RESOLVED" if status == "resolved" else "FIRING"
        names = ", ".join(a["name"] for a in alerts)
        subject = f"[{prefix}] Anima Alert: {names}"

        def _send_sync() -> bool:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(self.to_addrs)
            msg["Subject"] = subject
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15) as srv:
                    if self.smtp_user:
                        srv.login(self.smtp_user, self.smtp_password)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as srv:
                    srv.starttls()
                    if self.smtp_user:
                        srv.login(self.smtp_user, self.smtp_password)
                    srv.send_message(msg)
            return True

        try:
            return await asyncio.to_thread(_send_sync)
        except Exception:
            logger.exception("Email send failed")
            return False
