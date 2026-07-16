"""
NotifierBase ABC + @register_notifier decorator registry.

Usage:
    @register_notifier("discord")
    class DiscordNotifier(NotifierBase):
        async def send(self, alerts, status):
            ...
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar

_NOTIFIER_REGISTRY: dict[str, type["NotifierBase"]] = {}


class NotifierBase(ABC):
    """Abstract base class for notification channel plugins.

    Each subclass handles formatting and delivery for one channel
    (Discord, Feishu, Email, etc.).
    """

    name: ClassVar[str] = ""  # Set by decorator

    @abstractmethod
    async def send(self, alerts: list[dict], status: str) -> bool:
        """Send alert notifications to this channel.

        Args:
            alerts: List of parsed Alert dicts with fields:
                name, severity, summary, description, starts_at, status, labels
            status: Aggregate status from Alertmanager ("firing" or "resolved")

        Returns:
            True if delivery succeeded, False otherwise.
        """
        ...


def register_notifier(
    name: str,
) -> Callable[[type[NotifierBase]], type[NotifierBase]]:
    """Decorator: register a NotifierBase subclass under *name*.

    Usage::

        @register_notifier("discord")
        class DiscordNotifier(NotifierBase):
            ...
    """

    def decorator(cls: type[NotifierBase]) -> type[NotifierBase]:
        cls.name = name
        _NOTIFIER_REGISTRY[name] = cls
        return cls

    return decorator


def get_notifier_registry() -> dict[str, type[NotifierBase]]:
    """Return a copy of the notifier registry."""
    return dict(_NOTIFIER_REGISTRY)
