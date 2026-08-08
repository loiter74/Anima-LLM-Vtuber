from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from threading import Lock

from .models import (
    FailureAuthorization,
    FailureCircuitState,
    FailureRecord,
    FailureReflection,
    validate_sha256,
)
from .store import IterationPlanStore

_NORMALIZE_PARTS = re.compile(r"[^a-z0-9]+")


def _normalized(value: str) -> str:
    normalized = _NORMALIZE_PARTS.sub("-", value.casefold()).strip("-")
    if not normalized:
        raise ValueError("failure fingerprint fields must contain letters or digits")
    return normalized


def fingerprint_failure(
    *,
    step_kind: str,
    error_code: str,
    failure_layer: str,
    input_fingerprint: str,
    environment_fingerprint: str,
) -> str:
    validate_sha256(input_fingerprint, field_name="input_fingerprint")
    validate_sha256(environment_fingerprint, field_name="environment_fingerprint")
    material = {
        "environment_fingerprint": environment_fingerprint,
        "error_code": _normalized(error_code),
        "failure_layer": _normalized(failure_layer),
        "input_fingerprint": input_fingerprint,
        "step_kind": _normalized(step_kind),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class FailureLedger:
    def __init__(self, store: IterationPlanStore) -> None:
        self._store = store
        self._lock = Lock()

    def record(self, record: FailureRecord) -> FailureCircuitState:
        with self._lock:
            previous = self._store.read_failure_state(record.fingerprint)
            if previous is not None and previous.superseded_by is not None:
                raise RuntimeError("cannot record an occurrence against a superseded circuit")
            if previous is not None and previous.circuit_open:
                raise RuntimeError("cannot record an occurrence while the failure circuit is open")
            occurrences = (*previous.occurrences, record) if previous is not None else (record,)
            reflection = self._reflection(occurrences) if len(occurrences) >= 5 else None
            state = FailureCircuitState(
                fingerprint=record.fingerprint,
                occurrences=occurrences,
                circuit_open=reflection is not None,
                reflection=reflection,
            )
            self._store.write_failure_state(state)
            return state

    def authorize(self, fingerprint: str, *, run_id: str) -> FailureAuthorization:
        validate_sha256(fingerprint, field_name="fingerprint")
        state = self._store.read_failure_state(fingerprint)
        if state is None:
            return FailureAuthorization(allowed=True, reason="no matching failure recorded")
        if state.superseded_by is not None:
            return FailureAuthorization(
                allowed=False,
                reason="failure circuit was superseded by a new fingerprint",
                reflection=state.reflection,
            )
        if state.circuit_open:
            return FailureAuthorization(
                allowed=False,
                reason="failure circuit is open",
                reflection=state.reflection,
            )
        same_plan_count = sum(record.run_id == run_id for record in state.occurrences)
        if same_plan_count >= 3:
            return FailureAuthorization(
                allowed=False,
                reason="automatic retry limit reached for this plan",
            )
        return FailureAuthorization(allowed=True, reason="automatic retry remains available")

    def reset(
        self,
        fingerprint: str,
        *,
        new_fingerprint: str,
        reason: str,
        reset_at: datetime,
    ) -> FailureCircuitState:
        validate_sha256(fingerprint, field_name="fingerprint")
        validate_sha256(new_fingerprint, field_name="new_fingerprint")
        if fingerprint == new_fingerprint:
            raise ValueError("reset requires a changed failure fingerprint")
        if not reason.strip():
            raise ValueError("reset reason must not be empty")
        with self._lock:
            state = self._store.read_failure_state(fingerprint)
            if state is None:
                raise LookupError("cannot reset an unknown failure circuit")
            reset = FailureCircuitState.model_validate(
                {
                    **state.model_dump(mode="python"),
                    "circuit_open": False,
                    "superseded_by": new_fingerprint,
                    "reset_reason": reason.strip(),
                    "reset_at": reset_at,
                }
            )
            self._store.write_failure_state(reset)
            return reset

    @staticmethod
    def _reflection(occurrences: tuple[FailureRecord, ...]) -> FailureReflection:
        latest = occurrences[-1]

        def unique(values: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(dict.fromkeys(value for value in values if value))

        evidence = unique(tuple(ref for item in occurrences for ref in item.evidence_refs))
        excluded = unique(tuple(value for item in occurrences for value in item.excluded_causes))
        hypotheses = unique(
            tuple(value for item in occurrences for value in item.root_cause_hypotheses)
        )
        missing = unique(tuple(value for item in occurrences for value in item.missing_diagnostics))
        resources = unique(
            tuple(value for item in occurrences for value in item.affected_resources)
        )
        return FailureReflection(
            fingerprint=latest.fingerprint,
            occurrence_count=len(occurrences),
            evidence_refs=evidence,
            excluded_causes=excluded or ("different normalized input or environment state",),
            root_cause_hypotheses=hypotheses
            or (f"repeated {latest.failure_layer} failure at {latest.location}",),
            missing_diagnostics=missing or ("root-cause-specific diagnostic evidence",),
            affected_resources=resources or (f"step:{latest.step_id}",),
            next_action=(
                f"Stop automatic retries and diagnose {latest.location} before changing "
                "the relevant input or environment fingerprint."
            ),
            circuit_open=True,
        )
