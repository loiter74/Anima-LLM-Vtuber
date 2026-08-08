"""Trusted observation boundary around ordinary conversation tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Sanitized identity and arguments immediately before one real invocation."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    session_id: str
    conversation_id: str | None


@dataclass(frozen=True, slots=True)
class ToolInvocationCompletion:
    """Observed result without changing the tool node's execution semantics."""

    invocation: ToolInvocation
    result: Any | None
    error: str | None


class ToolInvocationObserver(Protocol):
    """Optional trusted hook; model output cannot configure this observer."""

    async def before_batch(self, invocations: tuple[ToolInvocation, ...]) -> None: ...

    async def before_invoke(self, invocation: ToolInvocation) -> None: ...

    async def after_invoke(self, completion: ToolInvocationCompletion) -> None: ...
