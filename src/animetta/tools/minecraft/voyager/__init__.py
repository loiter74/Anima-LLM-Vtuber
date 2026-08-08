"""Durable command-scoped Voyager control-plane domain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .control_plane import UnifiedVoyagerController
    from .gateway import ExecuteAtomicRequest, ExecuteMissionRequest, VoyagerGateway

__all__ = [
    "ExecuteAtomicRequest",
    "ExecuteMissionRequest",
    "UnifiedVoyagerController",
    "VoyagerGateway",
]


def __getattr__(name: str) -> Any:
    if name == "UnifiedVoyagerController":
        from .control_plane import UnifiedVoyagerController

        return UnifiedVoyagerController
    if name in {"ExecuteAtomicRequest", "ExecuteMissionRequest", "VoyagerGateway"}:
        from .gateway import ExecuteAtomicRequest, ExecuteMissionRequest, VoyagerGateway

        return {
            "ExecuteAtomicRequest": ExecuteAtomicRequest,
            "ExecuteMissionRequest": ExecuteMissionRequest,
            "VoyagerGateway": VoyagerGateway,
        }[name]
    raise AttributeError(name)
