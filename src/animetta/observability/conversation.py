"""Root conversation trace ownership and deterministic outcome reduction."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from contextvars import Token
from dataclasses import dataclass
from typing import Any

from .context import (
    ObservationContext,
    attach_observation_context,
    attach_observation_recorder,
    begin_delivery_evidence,
    delivery_evidence,
    detach_observation_context,
    detach_observation_recorder,
    end_delivery_evidence,
)
from .domain import (
    EventDirection,
    ObservationEvent,
    PrivacyMode,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from .errors import classify_error
from .ports import ObservationRecorder
from .privacy import ObservationContentPolicy


def reduce_trace_outcome(final_state: Mapping[str, Any]) -> TraceOutcome:
    if final_state.get("error"):
        return TraceOutcome.FAILED
    if not str(final_state.get("response_text") or "").strip():
        return TraceOutcome.FAILED

    metadata = final_state.get("metadata")
    if not isinstance(metadata, Mapping):
        return TraceOutcome.SUCCESS
    delivery = metadata.get("delivery")
    if isinstance(delivery, Mapping):
        if delivery.get("text_delivered") is False:
            return TraceOutcome.FAILED
        if delivery.get("terminal_control_delivered") is False:
            return TraceOutcome.FAILED
        if delivery.get("tts_required") and delivery.get("audio_delivered") is False:
            return TraceOutcome.DEGRADED
    if metadata.get("degradation_reason"):
        return TraceOutcome.DEGRADED
    if metadata.get("dialogue_status") in {"reasoner_failed", "composer_fallback"}:
        return TraceOutcome.DEGRADED
    return TraceOutcome.SUCCESS


class ConversationObserver:
    def __init__(
        self,
        recorder: ObservationRecorder,
        *,
        runtime_profile: str,
        digest_salt: str,
        privacy_mode: PrivacyMode | None = None,
    ) -> None:
        self._recorder = recorder
        self._runtime_profile = runtime_profile
        self._policy = (
            ObservationContentPolicy(privacy_mode, salt=digest_salt)
            if privacy_mode is not None
            else ObservationContentPolicy.for_profile(
                runtime_profile,
                salt=digest_salt,
            )
        )

    async def start(self, initial_state: Mapping[str, Any]) -> TurnObservation:
        identity = _identity(initial_state)
        if identity is None:
            return TurnObservation.unobserved()
        user_text = str(initial_state.get("user_text") or "")
        await self._recorder.start_trace(
            TraceStarted(
                identity=identity,
                runtime_profile=self._runtime_profile,
                input_type=str(initial_state.get("input_type") or "text"),
                privacy_mode=self._policy.mode,
                started_at=time.time(),
                user_content=self._policy.content_facts(user_text),
                attributes=self._policy.filter_attributes(
                    {
                        "runtime_profile": self._runtime_profile,
                        "input_type": initial_state.get("input_type"),
                    }
                ),
            )
        )
        await self._recorder.record_event(
            ObservationEvent(
                event_id=uuid.uuid4().hex,
                trace_id=identity.trace_id,
                operation_id=None,
                direction=EventDirection.INGRESS,
                name="chat:input",
                phase="accepted",
                occurred_at=time.time(),
                payload_size=len(user_text.encode("utf-8")),
                identity_valid=True,
                attributes={
                    "event_name": "chat:input",
                    "phase": "accepted",
                    "payload_size": len(user_text.encode("utf-8")),
                },
            )
        )
        context = ObservationContext(
            trace_id=identity.trace_id,
            operation_id=None,
            parent_operation_id=None,
            message_id=identity.message_id,
            conversation_id=identity.conversation_id,
            session_id=identity.session_id,
            privacy_mode=self._policy.mode,
        )
        token = attach_observation_context(context)
        recorder_token = attach_observation_recorder(self._recorder)
        delivery_token = begin_delivery_evidence()
        return TurnObservation(
            recorder=self._recorder,
            policy=self._policy,
            trace_id=identity.trace_id,
            token=token,
            delivery_token=delivery_token,
            recorder_token=recorder_token,
        )


@dataclass(slots=True)
class TurnObservation:
    recorder: ObservationRecorder | None
    policy: ObservationContentPolicy | None
    trace_id: str | None
    token: Token | None
    delivery_token: Token | None = None
    recorder_token: Token | None = None
    _finished: bool = False

    @classmethod
    def unobserved(cls) -> TurnObservation:
        return cls(None, None, None, None)

    async def finish(self, final_state: Mapping[str, Any]) -> None:
        effective_state = dict(final_state)
        evidence = delivery_evidence()
        if evidence.get("attempted"):
            effective_state["metadata"] = {
                **(
                    dict(final_state.get("metadata", {}))
                    if isinstance(final_state.get("metadata"), Mapping)
                    else {}
                ),
                "delivery": evidence,
            }
        await self._finish(reduce_trace_outcome(effective_state), effective_state)

    async def fail(self, error: BaseException) -> None:
        outcome = (
            TraceOutcome.CANCELLED
            if isinstance(error, asyncio.CancelledError)
            else TraceOutcome.FAILED
        )
        await self._finish(outcome, {}, error=error)

    async def _finish(
        self,
        outcome: TraceOutcome,
        final_state: Mapping[str, Any],
        *,
        error: BaseException | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            if self.recorder is None or self.policy is None or self.trace_id is None:
                return
            error_type = classify_error(error).value if error is not None else None
            await self.recorder.finish_trace(
                self.trace_id,
                outcome,
                finished_at=time.time(),
                error_type=error_type,
                error_summary=type(error).__name__ if error is not None else None,
                assistant_content=self.policy.content_facts(
                    str(final_state.get("response_text") or "")
                ),
                attributes=self.policy.filter_attributes(
                    {
                        "outcome": outcome.value,
                        "degradation_reason": _metadata_value(
                            final_state, "degradation_reason"
                        ),
                    }
                ),
            )
            await self.recorder.flush()
        finally:
            if self.token is not None:
                detach_observation_context(self.token)
            if self.delivery_token is not None:
                end_delivery_evidence(self.delivery_token)
            if self.recorder_token is not None:
                detach_observation_recorder(self.recorder_token)


def _identity(state: Mapping[str, Any]) -> TraceIdentity | None:
    values = {
        "message_id": state.get("message_id"),
        "conversation_id": state.get("conversation_id"),
        "task_id": state.get("task_id"),
        "session_id": state.get("session_id"),
    }
    if not all(isinstance(value, str) and value.strip() for value in values.values()):
        return None
    return TraceIdentity(**values)  # type: ignore[arg-type]


def _metadata_value(state: Mapping[str, Any], field: str) -> object:
    metadata = state.get("metadata")
    return metadata.get(field) if isinstance(metadata, Mapping) else None
