"""DeepSeek runtime model policy for Anima v0.1.

Defines routing between realtime roleplay (Flash, thinking disabled)
and complex reasoning (Pro, thinking enabled) modes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimePolicy:
    """Resolved model policy for a single LLM call."""
    mode: str
    model: str
    thinking: str  # "enabled" or "disabled"


# Pre-built policies
ROLEPLAY_REALTIME = RuntimePolicy(
    mode="roleplay_realtime",
    model="deepseek-v4-flash",
    thinking="disabled",
)

COMPLEX_REASONING = RuntimePolicy(
    mode="complex_reasoning",
    model="deepseek-v4-pro",
    thinking="enabled",
)

FALLBACK = RuntimePolicy(
    mode="fallback",
    model="deepseek-v4-flash",
    thinking="disabled",
)


def resolve_policy(
    channel_id: str | None = None,
    explicit_complex: bool = False,
) -> RuntimePolicy:
    """Resolve the runtime model policy for a given context.

    Args:
        channel_id: Channel identifier (e.g. "bilibili" for danmaku).
        explicit_complex: True when caller explicitly requests complex reasoning.

    Returns:
        RuntimePolicy with model and thinking mode.
    """
    if explicit_complex:
        return COMPLEX_REASONING

    # Bilibili/danmaku: always realtime roleplay
    if channel_id and "bilibili" in channel_id.lower():
        return ROLEPLAY_REALTIME

    # Default: realtime roleplay (Flash, thinking disabled)
    return ROLEPLAY_REALTIME
