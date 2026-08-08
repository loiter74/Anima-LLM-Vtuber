"""Independent skill-validation evidence and goal-derived verifier contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.voyager.goal_models import GoalSpec

from .ir import LiteralExpression, ObservationExpression, Predicate


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ValidationEvidenceChain(_FrozenModel):
    command_id: str = Field(min_length=1, max_length=256)
    correlation_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    receipt_refs: tuple[str, ...] = Field(min_length=1, max_length=128)
    start_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_instance_ref: str = Field(min_length=1, max_length=512)


class IndependentValidationEvidence(_FrozenModel):
    validation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    goal_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learning: ValidationEvidenceChain
    validation: ValidationEvidenceChain
    goal_verified: bool


class IndependentValidationDecision(_FrozenModel):
    validation_id: str
    trust_status: Literal["trusted", "candidate"]
    reason_code: Literal[
        "INDEPENDENT_VALIDATION_PASSED",
        "GOAL_CONTRACT_MISMATCH",
        "CORRELATED_EVIDENCE",
        "INSUFFICIENT_VALIDATION_VARIATION",
        "VALIDATION_FAILED",
    ]


def decide_independent_validation(
    evidence: IndependentValidationEvidence,
    *,
    expected_goal_contract_hash: str | None = None,
) -> IndependentValidationDecision:
    """Trust only a goal-verified run with independent evidence and conditions."""

    if (
        expected_goal_contract_hash is not None
        and evidence.goal_contract_hash != expected_goal_contract_hash
    ):
        return IndependentValidationDecision(
            validation_id=evidence.validation_id,
            trust_status="candidate",
            reason_code="GOAL_CONTRACT_MISMATCH",
        )
    correlated = bool(
        set(evidence.learning.correlation_ids) & set(evidence.validation.correlation_ids)
    ) or bool(set(evidence.learning.receipt_refs) & set(evidence.validation.receipt_refs))
    if correlated:
        return IndependentValidationDecision(
            validation_id=evidence.validation_id,
            trust_status="candidate",
            reason_code="CORRELATED_EVIDENCE",
        )
    if (
        evidence.learning.start_state_hash == evidence.validation.start_state_hash
        or evidence.learning.resource_instance_ref == evidence.validation.resource_instance_ref
    ):
        return IndependentValidationDecision(
            validation_id=evidence.validation_id,
            trust_status="candidate",
            reason_code="INSUFFICIENT_VALIDATION_VARIATION",
        )
    if not evidence.goal_verified:
        return IndependentValidationDecision(
            validation_id=evidence.validation_id,
            trust_status="candidate",
            reason_code="VALIDATION_FAILED",
        )
    return IndependentValidationDecision(
        validation_id=evidence.validation_id,
        trust_status="trusted",
        reason_code="INDEPENDENT_VALIDATION_PASSED",
    )


def _observation_at_least(path: str, value: int | float) -> Predicate:
    return Predicate(
        op="gte",
        left=ObservationExpression(kind="observation", path=path),
        right=LiteralExpression(kind="literal", value=value),
    )


def goal_postconditions(goal: GoalSpec) -> tuple[Predicate, ...]:
    """Compile typed goal success predicates into independently observable checks."""

    predicates: list[Predicate] = []
    for success in goal.success_predicates:
        if success.kind == "inventory_at_least":
            predicates.append(_observation_at_least(f"inventory.{success.item}", success.quantity))
        elif success.kind == "health_at_least":
            predicates.append(_observation_at_least("health", success.health))
        elif success.kind == "survived_duration":
            predicates.append(_observation_at_least("survival.duration_ms", success.duration_ms))
        elif success.kind == "entity_defeated":
            predicates.append(
                _observation_at_least(f"combat.defeated.{success.entity}", success.quantity)
            )
        elif success.kind == "blocks_placed":
            predicates.append(
                _observation_at_least(f"structure.blocks.{success.block}", success.quantity)
            )
        elif success.kind == "world_fact_observed":
            predicates.append(
                Predicate(
                    op="eq",
                    left=ObservationExpression(
                        kind="observation",
                        path=f"world_facts.{success.fact_kind}.{success.fact_key}",
                    ),
                    right=LiteralExpression(kind="literal", value=True),
                )
            )
        elif success.kind == "location_reached":
            for axis, coordinate in (
                ("x", success.x),
                ("y", success.y),
                ("z", success.z),
            ):
                predicates.extend(
                    (
                        _observation_at_least(f"position.{axis}", coordinate - success.tolerance),
                        Predicate(
                            op="lte",
                            left=ObservationExpression(kind="observation", path=f"position.{axis}"),
                            right=LiteralExpression(
                                kind="literal", value=coordinate + success.tolerance
                            ),
                        ),
                    )
                )
    if not predicates:
        raise ValueError("goal has no compilable verification predicate")
    return tuple(predicates)


def goal_contract_hash(predicates: tuple[Predicate, ...]) -> str:
    """Hash the exact immutable postconditions used for independent validation."""

    return canonical_json_hash([predicate.model_dump(mode="json") for predicate in predicates])
