"""Parameter-aware execution policy for model-selected tools."""

from __future__ import annotations

import errno
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ToolEffect(StrEnum):
    READ_ONLY = "read_only"
    STATE_CHANGING = "state_changing"
    UNKNOWN = "unknown"


class ToolPolicyError(RuntimeError):
    """Stable policy failure returned to the model and observation layer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ToolExecutionDecision:
    effect: ToolEffect
    timeout_seconds: float
    max_attempts: int
    requires_approval: bool = False


class ToolExecutionPolicy:
    """Classify tools using both trusted provenance and validated arguments."""

    _FILESYSTEM_READ_ONLY = frozenset(
        {
            "read_file",
            "read_text_file",
            "read_media_file",
            "list_directory",
            "list_directory_with_sizes",
            "directory_tree",
            "search_files",
            "get_file_info",
            "list_allowed_directories",
        }
    )

    def __init__(self, *, production: bool) -> None:
        self.production = production

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        tool_fn: Any,
    ) -> ToolExecutionDecision:
        source, server = _tool_provenance(tool_fn, tool_name)
        metadata = getattr(tool_fn, "metadata", None)
        declared_effect = metadata.get("effect") if isinstance(metadata, dict) else None
        effect, requires_approval = self._classify(
            tool_name,
            arguments,
            source=source,
            server=server,
            declared_effect=declared_effect,
        )
        if self.production and effect is ToolEffect.UNKNOWN:
            raise ToolPolicyError(
                "TOOL_POLICY_DENIED",
                f"Tool '{tool_name}' has no production side-effect classification",
            )
        if (
            self.production
            and source == "mcp"
            and server == "filesystem"
            and tool_name not in self._FILESYSTEM_READ_ONLY
        ):
            raise ToolPolicyError(
                "TOOL_POLICY_DENIED",
                f"Filesystem tool '{tool_name}' is not an explicit read-only capability",
            )
        if self.production and effect is ToolEffect.STATE_CHANGING and _is_sync_only(tool_fn):
            raise ToolPolicyError(
                "TOOL_POLICY_DENIED",
                f"Synchronous state-changing tool '{tool_name}' is not cancellable",
            )
        timeout = 5.0 if tool_name in {"calculator", "get_current_time", "time"} else 30.0
        if tool_name in {"web_search", "ddg_search"}:
            timeout = 20.0
        return ToolExecutionDecision(
            effect=effect,
            timeout_seconds=timeout,
            max_attempts=2 if effect is ToolEffect.READ_ONLY else 1,
            requires_approval=requires_approval and self.production,
        )

    def _classify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        source: str,
        server: str | None,
        declared_effect: Any,
    ) -> tuple[ToolEffect, bool]:
        if tool_name in {"calculator", "get_current_time", "time", "web_search", "ddg_search"}:
            return ToolEffect.READ_ONLY, False
        if tool_name == "mc_connection":
            operation = str(arguments.get("operation") or "")
            if operation == "status":
                return ToolEffect.READ_ONLY, False
            if operation in {"connect", "disconnect", "shutdown", "reattach_viewer"}:
                return ToolEffect.STATE_CHANGING, True
            return ToolEffect.UNKNOWN, False
        if tool_name == "mc_operate_bot":
            operation = str(arguments.get("operation") or "")
            if operation == "progress":
                return ToolEffect.READ_ONLY, False
            if operation in {"execute", "cancel"}:
                return ToolEffect.STATE_CHANGING, True
            return ToolEffect.UNKNOWN, False
        if declared_effect == ToolEffect.READ_ONLY:
            return ToolEffect.READ_ONLY, False
        if declared_effect == ToolEffect.STATE_CHANGING:
            return ToolEffect.STATE_CHANGING, False
        if source == "mcp":
            if server == "filesystem" and tool_name in self._FILESYSTEM_READ_ONLY:
                return ToolEffect.READ_ONLY, False
            return ToolEffect.UNKNOWN, False
        return ToolEffect.UNKNOWN, False


def is_transient_tool_error(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    return isinstance(exc, OSError) and exc.errno in {
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }


def _tool_provenance(tool_fn: Any, tool_name: str) -> tuple[str, str | None]:
    metadata = getattr(tool_fn, "metadata", None)
    if isinstance(metadata, dict):
        source = str(metadata.get("tool_source") or "builtin")
        server = metadata.get("mcp_server")
        return source, str(server) if server else None
    if tool_name.startswith("mc_"):
        return "minecraft", None
    return "builtin", None


def _is_sync_only(tool_fn: Any) -> bool:
    import inspect

    if hasattr(tool_fn, "coroutine"):
        return getattr(tool_fn, "coroutine") is None and getattr(tool_fn, "func", None) is not None
    if hasattr(tool_fn, "ainvoke"):
        return False
    if hasattr(tool_fn, "_arun"):
        return False
    return not inspect.iscoroutinefunction(tool_fn)
