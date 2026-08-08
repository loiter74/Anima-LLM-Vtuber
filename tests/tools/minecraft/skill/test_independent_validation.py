from __future__ import annotations

from importlib import import_module

from animetta.tools.minecraft.skill.revision_store import SkillRevisionStore
from animetta.tools.minecraft.skill.trust import TrustStatus

from .test_applicability_selection import _goal
from .test_skill_applicability import _revision


def _module():
    return import_module("animetta.tools.minecraft.skill.independent_validation")


def _chain(module, *, phase: str, start: str, resource: str):
    return module.ValidationEvidenceChain(
        command_id=f"{phase}-command-001",
        correlation_ids=(f"{phase}-correlation-001",),
        receipt_refs=(f"receipt:{phase}-001",),
        start_state_hash=start * 64,
        resource_instance_ref=resource,
    )


def _evidence(module, revision_hash: str, **updates: object):
    payload: dict[str, object] = {
        "validation_id": "validation-001",
        "revision_hash": revision_hash,
        "environment_fingerprint": "e" * 64,
        "goal_contract_hash": "c" * 64,
        "learning": _chain(
            module,
            phase="learning",
            start="a",
            resource="block:overworld:10:64:10",
        ),
        "validation": _chain(
            module,
            phase="validation",
            start="b",
            resource="block:overworld:24:63:18",
        ),
        "goal_verified": True,
    }
    payload.update(updates)
    return module.IndependentValidationEvidence.model_validate(payload)


def test_validation_requires_distinct_chains_and_varied_start_resource_conditions() -> None:
    module = _module()
    _, revision = _revision()
    valid = _evidence(module, revision.revision_hash)
    correlated = valid.model_copy(
        update={
            "validation": valid.validation.model_copy(
                update={"correlation_ids": valid.learning.correlation_ids}
            )
        }
    )
    same_conditions = valid.model_copy(
        update={
            "validation": valid.validation.model_copy(
                update={
                    "start_state_hash": valid.learning.start_state_hash,
                    "resource_instance_ref": valid.learning.resource_instance_ref,
                }
            )
        }
    )

    assert module.decide_independent_validation(valid).trust_status == "trusted"
    assert module.decide_independent_validation(correlated).reason_code == ("CORRELATED_EVIDENCE")
    assert module.decide_independent_validation(same_conditions).reason_code == (
        "INSUFFICIENT_VALIDATION_VARIATION"
    )


def test_goal_contract_uses_goal_predicate_instead_of_tautological_health_check() -> None:
    module = _module()

    predicates = module.goal_postconditions(_goal())

    assert len(predicates) == 1
    assert predicates[0].left.path == "inventory.minecraft:raw_copper"
    assert predicates[0].right.value == 2
    assert all(predicate.left.path != "health" for predicate in predicates)


async def test_failed_independent_validation_persists_as_untrusted(tmp_path) -> None:
    module = _module()
    definition, revision = _revision()
    store = SkillRevisionStore(tmp_path / "skills.db")
    await store.connect()
    try:
        await store.save_revision(definition, revision)
        failed = _evidence(
            module,
            revision.revision_hash,
            goal_contract_hash=module.goal_contract_hash(revision.program.postconditions),
            goal_verified=False,
        )
        trust = await store.record_independent_validation(
            failed,
            policy_report={"valid": True},
            expected_cost=2,
            portable=False,
        )
        _, trusts = await store.load_live_catalog(
            environment_fingerprint=failed.environment_fingerprint
        )
    finally:
        await store.close()

    assert trust.status is TrustStatus.CANDIDATE
    assert trusts[0].status is TrustStatus.CANDIDATE


async def test_independent_validation_with_matching_goal_contract_becomes_trusted(
    tmp_path,
) -> None:
    module = _module()
    definition, revision = _revision()
    store = SkillRevisionStore(tmp_path / "skills.db")
    await store.connect()
    try:
        await store.save_revision(definition, revision)
        evidence = _evidence(
            module,
            revision.revision_hash,
            goal_contract_hash=module.goal_contract_hash(revision.program.postconditions),
        )
        trust = await store.record_independent_validation(
            evidence,
            policy_report={"valid": True},
            expected_cost=2,
            portable=False,
        )
        restored = await store.load_independent_validation_evidence(
            revision_hash=revision.revision_hash,
            environment_fingerprint=evidence.environment_fingerprint,
        )
    finally:
        await store.close()

    assert trust.status is TrustStatus.TRUSTED
    assert restored == (evidence,)
