"""Trusted observation boundary around ordinary conversation tool calls."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from animetta.observability.context import get_observation_context
from animetta.observability.domain import (
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
)
from animetta.observability.ports import ObservationRecorder
from animetta.observability.privacy import ObservationContentPolicy


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Sanitized identity and arguments immediately before one real invocation."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    session_id: str
    conversation_id: str | None
    tool_source: str = "builtin"
    mcp_server: str | None = None


@dataclass(frozen=True, slots=True)
class ToolInvocationCompletion:
    """Observed result without changing the tool node's execution semantics."""

    invocation: ToolInvocation
    result: Any | None
    error: str | None
    cancelled: bool = False
    retry_count: int = 0
    approval_result: str | None = None
    error_code: str | None = None
    tool_effect: str | None = None


class ToolInvocationObserver(Protocol):
    """Optional trusted hook; model output cannot configure this observer."""

    async def before_batch(self, invocations: tuple[ToolInvocation, ...]) -> None: ...

    async def before_invoke(self, invocation: ToolInvocation) -> None: ...

    async def after_invoke(self, completion: ToolInvocationCompletion) -> None: ...

    async def record_policy_failure(
        self,
        invocations: tuple[ToolInvocation, ...],
        code: str,
    ) -> None: ...

    async def record_approval(
        self,
        invocations: tuple[ToolInvocation, ...],
        result: str,
    ) -> None: ...


class LedgerToolInvocationObserver:
    """Record exactly one operation around each real tool invocation."""

    def __init__(self, recorder: ObservationRecorder, *, digest_salt: str) -> None:
        self._recorder = recorder
        self._digest_salt = digest_salt
        self._active: dict[
            str,
            tuple[str, ObservationContentPolicy, dict[str, str | int | None]],
        ] = {}

    async def before_batch(self, invocations: tuple[ToolInvocation, ...]) -> None:
        del invocations

    async def before_invoke(self, invocation: ToolInvocation) -> None:
        context = get_observation_context()
        if context is None:
            return
        operation_id = uuid.uuid4().hex
        policy = ObservationContentPolicy(context.privacy_mode, salt=self._digest_salt)
        arguments = _json_text(invocation.arguments)
        attributes = {
            "tool_call_id": invocation.tool_call_id,
            "tool_name": invocation.tool_name,
            "tool_source": invocation.tool_source,
            "mcp_server": invocation.mcp_server,
            **_content_attributes("arguments", policy, arguments),
        }
        filtered_attributes = policy.filter_attributes(attributes)
        await self._recorder.start_operation(
            OperationStarted(
                operation_id=operation_id,
                trace_id=context.trace_id,
                parent_operation_id=context.operation_id or context.parent_operation_id,
                layer=ObservationLayer.SERVICE,
                name=f"tool:{invocation.tool_name}",
                critical_path=True,
                started_at=time.time(),
                attributes=filtered_attributes,
            )
        )
        self._active[invocation.tool_call_id] = (
            operation_id,
            policy,
            filtered_attributes,
        )

    async def after_invoke(self, completion: ToolInvocationCompletion) -> None:
        active = self._active.pop(completion.invocation.tool_call_id, None)
        if active is None:
            return
        operation_id, policy, base_attributes = active
        result_text = _json_text(completion.result)
        result_attributes = _content_attributes("result", policy, result_text)
        command_id, request_id = _minecraft_ids(completion.result)
        if command_id:
            result_attributes["minecraft_command_id"] = command_id
        if request_id:
            result_attributes["minecraft_request_id"] = request_id
        result_attributes["retry_count"] = completion.retry_count
        if completion.approval_result:
            result_attributes["approval_result"] = completion.approval_result
        if completion.tool_effect:
            result_attributes["tool_effect"] = completion.tool_effect
        if completion.error:
            status = OperationStatus.CANCELLED if completion.cancelled else OperationStatus.ERROR
            error = policy.sanitize_error(completion.error, error_type="tool_error")
            await self._recorder.finish_operation(
                OperationFinished(
                    operation_id=operation_id,
                    status=status,
                    finished_at=time.time(),
                    error_type=completion.error_code or error.error_type,
                    error_summary=error.summary,
                    attributes={
                        **base_attributes,
                        **policy.filter_attributes(result_attributes),
                    },
                )
            )
            return
        await self._recorder.finish_operation(
            OperationFinished(
                operation_id=operation_id,
                status=OperationStatus.SUCCESS,
                finished_at=time.time(),
                attributes={
                    **base_attributes,
                    **policy.filter_attributes(result_attributes),
                },
            )
        )

    async def record_policy_failure(
        self,
        invocations: tuple[ToolInvocation, ...],
        code: str,
    ) -> None:
        for invocation in invocations:
            await self._record_decision(
                invocation,
                name=f"tool_policy:{invocation.tool_name}",
                status=OperationStatus.ERROR,
                error_type=code,
                attributes={"tool_name": invocation.tool_name},
            )

    async def record_approval(
        self,
        invocations: tuple[ToolInvocation, ...],
        result: str,
    ) -> None:
        status = OperationStatus.SUCCESS if result == "approve" else OperationStatus.CANCELLED
        for invocation in invocations:
            await self._record_decision(
                invocation,
                name=f"approval:{invocation.tool_name}",
                status=status,
                error_type=None if result == "approve" else "APPROVAL_REJECTED",
                attributes={
                    "tool_name": invocation.tool_name,
                    "approval_result": result,
                },
            )

    async def _record_decision(
        self,
        invocation: ToolInvocation,
        *,
        name: str,
        status: OperationStatus,
        error_type: str | None,
        attributes: dict[str, str],
    ) -> None:
        context = get_observation_context()
        if context is None:
            return
        operation_id = uuid.uuid4().hex
        now = time.time()
        await self._recorder.start_operation(
            OperationStarted(
                operation_id=operation_id,
                trace_id=context.trace_id,
                parent_operation_id=context.operation_id or context.parent_operation_id,
                layer=ObservationLayer.WORKFLOW,
                name=name,
                critical_path=True,
                started_at=now,
                attributes=attributes,
            )
        )
        await self._recorder.finish_operation(
            OperationFinished(
                operation_id=operation_id,
                status=status,
                finished_at=now,
                error_type=error_type,
                error_summary=error_type,
                attributes=attributes,
            )
        )


class CompositeToolInvocationObserver:
    """Preserve explicit observer semantics while always completing ledger hooks."""

    def __init__(self, *observers: ToolInvocationObserver) -> None:
        self._observers = observers

    async def before_batch(self, invocations: tuple[ToolInvocation, ...]) -> None:
        for observer in self._observers:
            await observer.before_batch(invocations)

    async def before_invoke(self, invocation: ToolInvocation) -> None:
        for observer in self._observers:
            await observer.before_invoke(invocation)

    async def after_invoke(self, completion: ToolInvocationCompletion) -> None:
        first_error: Exception | None = None
        for observer in self._observers:
            try:
                await observer.after_invoke(completion)
            except Exception as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    async def record_policy_failure(
        self,
        invocations: tuple[ToolInvocation, ...],
        code: str,
    ) -> None:
        for observer in self._observers:
            callback = getattr(observer, "record_policy_failure", None)
            if callback is not None:
                await callback(invocations, code)

    async def record_approval(
        self,
        invocations: tuple[ToolInvocation, ...],
        result: str,
    ) -> None:
        for observer in self._observers:
            callback = getattr(observer, "record_approval", None)
            if callback is not None:
                await callback(invocations, result)


def _content_attributes(
    prefix: str,
    policy: ObservationContentPolicy,
    text: str,
) -> dict[str, str | int | None]:
    facts = policy.content_facts(text)
    return {
        f"{prefix}_text": facts.text,
        f"{prefix}_character_count": facts.character_count,
        f"{prefix}_byte_count": facts.byte_count,
        f"{prefix}_digest": facts.digest,
    }


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _minecraft_ids(value: Any) -> tuple[str | None, str | None]:
    data = value
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):
            return None, None
    if not isinstance(data, dict):
        return None, None
    command_id = data.get("command_id") or data.get("stop_command_id")
    request_id = data.get("request_id")
    receipt = data.get("receipt")
    if isinstance(receipt, dict):
        command_id = command_id or receipt.get("command_id")
        request_id = request_id or receipt.get("request_id")
    return (
        str(command_id) if command_id else None,
        str(request_id) if request_id else None,
    )
