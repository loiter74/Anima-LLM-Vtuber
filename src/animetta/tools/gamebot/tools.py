"""Generic tool adapter — wraps GameBotClient.send_command as a LangChain tool helper.

Does NOT import any Minecraft-specific config, item names, or action names.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def create_tool_helper(
    send_command: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[str]]:
    """Create an async helper that calls send_command and formats the result for LLM tools.

    Args:
        send_command: An async callable with signature
            ``(action: str, params: dict, timeout: float) -> dict``
            that returns a bridge-style ``{"status": ..., "result": ...}`` dict.

    Returns:
        An async helper ``helper(action, params, *, timeout) -> str``.
    """

    async def _helper(
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> str:
        result = await send_command(action, params or {}, timeout)

        status = result.get("status", "error")
        payload = result.get("result", "No result returned")

        if status == "error":
            return f"Action failed: {payload}"

        # Dict results → formatted text
        if isinstance(payload, dict):
            lines: list[str] = []
            for key, value in payload.items():
                if isinstance(value, dict):
                    lines.append(f"{key}: {value}")
                elif isinstance(value, list):
                    lines.append(f"{key}: {', '.join(str(v) for v in value)}")
                else:
                    lines.append(f"{key}: {value}")
            return "\n".join(lines)

        return str(payload)

    return _helper
