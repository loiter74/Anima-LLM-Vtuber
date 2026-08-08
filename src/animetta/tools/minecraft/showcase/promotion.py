"""Durable R0-R8 promotion and stop-the-line failure accounting."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

GateName = Literal["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
GateStatus = Literal["passed", "failed", "blocked"]
FailureLayer = Literal[
    "scenario",
    "capture",
    "conversation",
    "admission",
    "execution",
    "observation",
    "reconciliation",
    "verification",
    "presentation",
]

GATE_ORDER: tuple[GateName, ...] = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8")
_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$"
_HASH = r"^[0-9a-f]{64}$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PromotionIdentity(_FrozenModel):
    schema_version: Literal["1"] = "1"
    code_commit: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-f]+$")
    code_tree_hash: str = Field(pattern=_HASH)
    runtime_identity: str = Field(min_length=1, max_length=256)
    minecraft_version: str = Field(min_length=1, max_length=64)
    scenario_hash: str = Field(pattern=_HASH)
    model_identity: str = Field(min_length=1, max_length=256)
    schema_hashes: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def _schema_hashes_are_canonical(self) -> Self:
        if any(not key or not _is_hash(value) for key, value in self.schema_hashes.items()):
            raise ValueError("schema hashes must use non-empty names and sha256 values")
        return self

    def fingerprint_for(self, gate: GateName) -> str:
        ordinal = GATE_ORDER.index(gate)
        payload: dict[str, object] = {
            "code_commit": self.code_commit,
            "code_tree_hash": self.code_tree_hash,
        }
        if ordinal >= 1:
            payload["schema_hashes"] = dict(sorted(self.schema_hashes.items()))
        if ordinal >= 2:
            payload["scenario_hash"] = self.scenario_hash
        if ordinal >= 5:
            payload["runtime_identity"] = self.runtime_identity
            payload["minecraft_version"] = self.minecraft_version
        if ordinal >= 6:
            payload["model_identity"] = self.model_identity
        return canonical_json_hash(payload)


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class GateResult(_FrozenModel):
    schema_version: Literal["1"] = "1"
    gate: GateName
    status: GateStatus
    attempt_id: str = Field(pattern=_SAFE_ID)
    identity_fingerprint: str = Field(pattern=_HASH)
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")

    @model_validator(mode="after")
    def _consistent_result(self) -> Self:
        if self.finished_at_ms < self.started_at_ms:
            raise ValueError("gate finish precedes start")
        if self.status == "passed" and self.failure_code is not None:
            raise ValueError("passed gate cannot contain a failure code")
        if self.status != "passed" and self.failure_code is None:
            raise ValueError("non-passed gate requires a failure code")
        return self


class RealAttempt(_FrozenModel):
    schema_version: Literal["1"] = "1"
    attempt_id: str = Field(pattern=_SAFE_ID)
    run_id: str = Field(pattern=_SAFE_ID)
    stage_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    outcome: Literal["passed", "failed"]
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    failure_layer: FailureLayer | None = None
    occurred_at_ms: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _failure_is_classified(self) -> Self:
        failed = self.outcome == "failed"
        if failed != (self.failure_code is not None and self.failure_layer is not None):
            raise ValueError("real failure requires a code and classified layer")
        return self


class FailureCoverage(_FrozenModel):
    schema_version: Literal["1"] = "1"
    stage_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    deterministic_r4_ref: str = Field(min_length=1, max_length=512)
    minimal_r7_ref: str = Field(min_length=1, max_length=512)
    recorded_at_ms: int = Field(ge=0)


class ArchitectureAudit(_FrozenModel):
    schema_version: Literal["1"] = "1"
    overall_failure_cause: str = Field(min_length=1, max_length=2_000)
    contributing_causes: tuple[str, ...] = Field(min_length=1)
    systemic_changes: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    recorded_at_ms: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class FailureBudgetStatus:
    total_failures: int
    failures_by_stage: dict[str, int]
    r7_allowed: bool
    r8_allowed: bool
    required_actions: tuple[str, ...]


class AcceptanceLedger(_FrozenModel):
    schema_version: Literal["1"] = "1"
    identity: PromotionIdentity
    gate_results: tuple[GateResult, ...] = ()
    real_attempts: tuple[RealAttempt, ...] = ()
    failure_coverages: tuple[FailureCoverage, ...] = ()
    architecture_audit: ArchitectureAudit | None = None

    def _latest_current_gate(self, gate: GateName) -> GateResult | None:
        fingerprint = self.identity.fingerprint_for(gate)
        return next(
            (
                result
                for result in reversed(self.gate_results)
                if result.gate == gate and result.identity_fingerprint == fingerprint
            ),
            None,
        )

    @property
    def highest_current_passed_gate(self) -> GateName | None:
        highest: GateName | None = None
        for gate in GATE_ORDER:
            result = self._latest_current_gate(gate)
            if result is None or result.status != "passed":
                break
            highest = gate
        return highest

    def can_promote(self, gate: GateName) -> bool:
        ordinal = GATE_ORDER.index(gate)
        return all(
            (result := self._latest_current_gate(prior)) is not None and result.status == "passed"
            for prior in GATE_ORDER[:ordinal]
        )

    def require_gate_start(self, gate: GateName) -> None:
        budget = self.failure_budget
        if gate == "R7" and not budget.r7_allowed:
            raise ValueError("REAL_GATE_BLOCKED:" + ",".join(budget.required_actions))
        if gate == "R8" and not budget.r8_allowed:
            raise ValueError("REAL_GATE_BLOCKED:" + ",".join(budget.required_actions))
        if not self.can_promote(gate):
            raise ValueError("PRIOR_GATE_NOT_PROMOTED")

    def rebind_identity(self, identity: PromotionIdentity) -> Self:
        return self.model_copy(update={"identity": identity})

    def record_gate(
        self,
        *,
        gate: GateName,
        status: GateStatus,
        attempt_id: str,
        started_at_ms: int,
        finished_at_ms: int,
        evidence_refs: tuple[str, ...],
        failure_code: str | None = None,
    ) -> Self:
        if any(result.attempt_id == attempt_id for result in self.gate_results):
            raise ValueError("DUPLICATE_GATE_ATTEMPT")
        if status == "passed" and not self.can_promote(gate):
            raise ValueError("PRIOR_GATE_NOT_PROMOTED")
        result = GateResult(
            gate=gate,
            status=status,
            attempt_id=attempt_id,
            identity_fingerprint=self.identity.fingerprint_for(gate),
            started_at_ms=started_at_ms,
            finished_at_ms=finished_at_ms,
            evidence_refs=evidence_refs,
            failure_code=failure_code,
        )
        return self.model_copy(update={"gate_results": (*self.gate_results, result)})

    def record_real_attempt(self, attempt: RealAttempt) -> Self:
        if any(
            prior.attempt_id == attempt.attempt_id or prior.run_id == attempt.run_id
            for prior in self.real_attempts
        ):
            raise ValueError("DUPLICATE_REAL_ATTEMPT")
        return self.model_copy(update={"real_attempts": (*self.real_attempts, attempt)})

    def add_failure_coverage(self, coverage: FailureCoverage) -> Self:
        retained = tuple(
            item for item in self.failure_coverages if item.stage_id != coverage.stage_id
        )
        return self.model_copy(update={"failure_coverages": (*retained, coverage)})

    def record_architecture_audit(self, audit: ArchitectureAudit) -> Self:
        if self.failure_budget.total_failures < 5:
            raise ValueError("ARCHITECTURE_AUDIT_NOT_REQUIRED")
        return self.model_copy(update={"architecture_audit": audit})

    @property
    def failure_budget(self) -> FailureBudgetStatus:
        failures = tuple(item for item in self.real_attempts if item.outcome == "failed")
        by_stage = dict(Counter(item.stage_id for item in failures))
        coverage_stages = {item.stage_id for item in self.failure_coverages}
        repeated_without_coverage = tuple(
            sorted(
                stage_id
                for stage_id, count in by_stage.items()
                if count >= 2 and stage_id not in coverage_stages
            )
        )
        audit_required = len(failures) >= 5 and self.architecture_audit is None
        r7_allowed = not audit_required
        r8_allowed = r7_allowed and not repeated_without_coverage
        required_actions: tuple[str, ...]
        if audit_required:
            required_actions = ("PERFORM_OVERALL_ARCHITECTURE_AUDIT",)
        else:
            required_actions = tuple(
                f"{stage_id}:ADD_MINIMAL_R7_REPRODUCTION_AND_R4_REPLAY"
                for stage_id in repeated_without_coverage
            )
        return FailureBudgetStatus(
            total_failures=len(failures),
            failures_by_stage=by_stage,
            r7_allowed=r7_allowed,
            r8_allowed=r8_allowed,
            required_actions=required_actions,
        )


class AcceptanceLedgerStore:
    """Atomically persist the cross-run ledger so a new run ID cannot reset it."""

    def __init__(self, path: Path) -> None:
        self._path = path.resolve()

    def save(self, ledger: AcceptanceLedger) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self._path)

    def load(self) -> AcceptanceLedger:
        return AcceptanceLedger.model_validate_json(self._path.read_text(encoding="utf-8"))
