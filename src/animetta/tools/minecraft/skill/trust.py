"""Environment-scoped trust, execution attribution, demotion, and ranking."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import (
    EnvironmentProfile,
    canonical_json_hash,
)


class TrustStatus(StrEnum):
    CANDIDATE = "candidate"
    TRUSTED = "trusted"
    DEMOTED = "demoted"
    QUARANTINED = "quarantined"
    LEGACY_UNTRUSTED = "legacy_untrusted"


class ExecutionAttribution(StrEnum):
    SUCCESS = "success"
    ATTRIBUTABLE_FAILURE = "attributable_failure"
    ENVIRONMENT_FAILURE = "environment_failure"
    CALLER_FAILURE = "caller_failure"
    RUNTIME_FAILURE = "runtime_failure"
    POLICY_VIOLATION = "policy_violation"
    UNEXPLAINED_MUTATION = "unexplained_mutation"


def stable_environment_fingerprint(
    profile: EnvironmentProfile, *, transient: dict[str, object] | None = None
) -> str:
    """Hash only stable profile fields; transient observations are intentionally ignored."""

    del transient
    return canonical_json_hash(profile.model_dump(mode="json"))


class SkillEnvironmentTrust(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: TrustStatus
    successes: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    consecutive_failures: int = Field(default=0, ge=0)
    expected_cost: float = Field(default=0, ge=0)
    portable: bool = False
    revision_quarantined: bool = False
    demotion_reason: str = ""

    @classmethod
    def trusted(
        cls,
        revision_hash: str,
        environment_fingerprint: str,
        *,
        successes: int = 0,
        failures: int = 0,
        expected_cost: float = 0,
        portable: bool = False,
    ) -> SkillEnvironmentTrust:
        return cls(
            revision_hash=revision_hash,
            environment_fingerprint=environment_fingerprint,
            status=TrustStatus.TRUSTED,
            successes=successes,
            failures=failures,
            expected_cost=expected_cost,
            portable=portable,
        )

    @property
    def wilson_reliability(self) -> float:
        total = self.successes + self.failures
        if total == 0:
            return 0.0
        z = 1.96
        proportion = self.successes / total
        denominator = 1 + z * z / total
        centre = proportion + z * z / (2 * total)
        margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
        return (centre - margin) / denominator

    def is_eligible(self, environment_fingerprint: str) -> bool:
        return (
            self.status is TrustStatus.TRUSTED
            and not self.revision_quarantined
            and self.environment_fingerprint == environment_fingerprint
        )


def apply_execution_outcome(
    trust: SkillEnvironmentTrust,
    attribution: ExecutionAttribution,
    *,
    demotion_threshold: int,
) -> SkillEnvironmentTrust:
    if attribution is ExecutionAttribution.SUCCESS:
        return trust.model_copy(
            update={
                "successes": trust.successes + 1,
                "consecutive_failures": 0,
            }
        )
    if attribution is ExecutionAttribution.ATTRIBUTABLE_FAILURE:
        failures = trust.failures + 1
        consecutive = trust.consecutive_failures + 1
        demoted = consecutive >= demotion_threshold
        return trust.model_copy(
            update={
                "failures": failures,
                "consecutive_failures": consecutive,
                "status": TrustStatus.DEMOTED if demoted else trust.status,
                "demotion_reason": "ordinary attributable failure threshold"
                if demoted
                else trust.demotion_reason,
            }
        )
    if attribution in {
        ExecutionAttribution.POLICY_VIOLATION,
        ExecutionAttribution.UNEXPLAINED_MUTATION,
    }:
        return trust.model_copy(
            update={
                "status": TrustStatus.QUARANTINED,
                "revision_quarantined": True,
                "demotion_reason": attribution.value,
            }
        )
    return trust


def rank_trusted_revisions(
    records: list[SkillEnvironmentTrust], *, environment_fingerprint: str
) -> list[SkillEnvironmentTrust]:
    eligible = [record for record in records if record.is_eligible(environment_fingerprint)]
    return sorted(
        eligible,
        key=lambda record: (
            -record.wilson_reliability,
            record.expected_cost,
            record.revision_hash,
        ),
    )
