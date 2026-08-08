"""Additive skill migration, environment trust, attribution, and ranking."""

from __future__ import annotations

import sqlite3

from animetta.tools.gamebot.contracts.v2 import EnvironmentProfile
from animetta.tools.minecraft.skill.ir import (
    SkillDefinition,
    SkillProgram,
    compile_skill_program,
)
from animetta.tools.minecraft.skill.revision_store import (
    SkillRevisionStore,
    convert_legacy_skill,
)
from animetta.tools.minecraft.skill.trust import (
    ExecutionAttribution,
    SkillEnvironmentTrust,
    TrustStatus,
    apply_execution_outcome,
    rank_trusted_revisions,
    stable_environment_fingerprint,
)
from animetta.tools.minecraft.voyager.budget import BudgetUsage, ExecutionBudget


def _profile(*, world_hash: str = "c" * 64) -> EnvironmentProfile:
    return EnvironmentProfile(
        runtime_protocol="2.0",
        minecraft_version="1.21.1",
        capability_schema_digest="a" * 64,
        skill_api_version="1",
        policy_version="1",
        server_identity_hash="b" * 64,
        world_identity_hash=world_hash,
        dimension="minecraft:overworld",
        modset_digest="d" * 64,
    )


async def test_legacy_migration_is_additive_and_all_executable_rows_are_untrusted(
    tmp_path,
) -> None:
    path = tmp_path / "skills.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE skills (
        id TEXT PRIMARY KEY, name TEXT, description TEXT, body_json TEXT,
        steps_json TEXT, is_learned INTEGER, validated INTEGER,
        success_count INTEGER, fail_count INTEGER
        )"""
    )
    rows = [
        ("predefined", "Predefined", "", "{}", "[]", 0, 1, 0, 0),
        ("learned", "Learned", "", "{}", '[{"name":"collect","params":{}}]', 1, 0, 0, 0),
        ("code", "Code", "", '{"type":"code","code":"await collect()"}', "[]", 1, 1, 2, 0),
        ("validated", "Validated", "", "{}", '[{"name":"collect","params":{}}]', 1, 1, 5, 0),
        ("failed", "Failed", "", "{}", '[{"name":"collect","params":{}}]', 1, 0, 0, 4),
    ]
    connection.executemany("INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()

    store = SkillRevisionStore(path)
    await store.connect()
    try:
        migrated = await store.migrate_legacy_skills()
        records = await store.legacy_migrations()
    finally:
        await store.close()

    assert migrated == 5
    assert {record["migration_status"] for record in records} == {"legacy_untrusted"}
    check = sqlite3.connect(path)
    try:
        assert check.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 5
        assert check.execute("SELECT validated FROM skills WHERE id='validated'").fetchone()[0] == 1
    finally:
        check.close()


def test_offline_converter_creates_candidate_ir_without_trust() -> None:
    candidate = convert_legacy_skill(
        {
            "id": "collect_log",
            "name": "Collect log",
            "description": "",
            "steps": [{"name": "collect", "params": {"block_type": "oak_log", "count": 1}}],
        }
    )

    assert candidate is not None
    assert candidate.trust_status is TrustStatus.CANDIDATE
    assert candidate.program.steps[0].kind == "action"


def test_stable_environment_identity_ignores_transient_observation_state() -> None:
    profile = _profile()
    first = stable_environment_fingerprint(
        profile,
        transient={"weather": "rain", "health": 4, "position": [1, 2, 3]},
    )
    second = stable_environment_fingerprint(
        profile,
        transient={"weather": "clear", "health": 20, "inventory": {"log": 2}},
    )

    assert first == second
    assert stable_environment_fingerprint(_profile(world_hash="e" * 64)) != first


def test_portability_never_inherits_environment_trust() -> None:
    source = SkillEnvironmentTrust.trusted(
        revision_hash="1" * 64,
        environment_fingerprint=stable_environment_fingerprint(_profile()),
        portable=True,
    )
    destination = stable_environment_fingerprint(_profile(world_hash="e" * 64))

    assert source.is_eligible(destination) is False


def test_attribution_demotes_environment_but_policy_quarantines_revision() -> None:
    trust = SkillEnvironmentTrust.trusted(
        revision_hash="1" * 64,
        environment_fingerprint="2" * 64,
    )
    environment_failure = apply_execution_outcome(
        trust, ExecutionAttribution.ENVIRONMENT_FAILURE, demotion_threshold=2
    )
    first_failure = apply_execution_outcome(
        environment_failure, ExecutionAttribution.ATTRIBUTABLE_FAILURE, demotion_threshold=2
    )
    demoted = apply_execution_outcome(
        first_failure, ExecutionAttribution.ATTRIBUTABLE_FAILURE, demotion_threshold=2
    )
    quarantined = apply_execution_outcome(
        trust, ExecutionAttribution.UNEXPLAINED_MUTATION, demotion_threshold=2
    )

    assert environment_failure.failures == 0
    assert demoted.status is TrustStatus.DEMOTED
    assert quarantined.status is TrustStatus.QUARANTINED
    assert quarantined.revision_quarantined is True


def test_ranking_uses_wilson_reliability_cost_and_stable_revision_tie_break() -> None:
    trusts = [
        SkillEnvironmentTrust.trusted("b" * 64, "e" * 64, successes=8, failures=2, expected_cost=3),
        SkillEnvironmentTrust.trusted("a" * 64, "e" * 64, successes=8, failures=2, expected_cost=3),
        SkillEnvironmentTrust.trusted("c" * 64, "e" * 64, successes=2, failures=0, expected_cost=1),
    ]

    ranked = rank_trusted_revisions(trusts, environment_fingerprint="e" * 64)

    assert [record.revision_hash for record in ranked] == ["a" * 64, "b" * 64, "c" * 64]


async def test_revision_and_environment_trust_round_trip(tmp_path) -> None:
    store = SkillRevisionStore(tmp_path / "skills.db")
    await store.connect()
    try:
        program = SkillProgram.model_validate(
            {
                "name": "collect_log",
                "steps": [
                    {
                        "kind": "action",
                        "step_id": "collect",
                        "capability": "collect",
                        "parameters": {"count": {"kind": "literal", "value": 1}},
                    }
                ],
                "postconditions": [
                    {
                        "op": "gte",
                        "left": {"kind": "observation", "path": "inventory.oak_log"},
                        "right": {"kind": "literal", "value": 1},
                    }
                ],
            }
        )
        compiled = compile_skill_program(
            program,
            capabilities={
                "collect": {
                    "parameters_schema": {
                        "type": "object",
                        "properties": {"count": {"type": "integer"}},
                        "required": ["count"],
                        "additionalProperties": False,
                    },
                    "maximum_cost": BudgetUsage(max_actions=1),
                }
            },
            budget=ExecutionBudget(
                queue_timeout_ms=100,
                execution_timeout_ms=1_000,
                max_actions=2,
                max_strategy_attempts=1,
                max_travel_distance=10,
                max_blocks_changed=2,
                max_damage_taken=1,
            ),
        )
        definition = SkillDefinition(
            definition_id="collect_log", name="collect_log", description=""
        )
        revision = compiled.to_revision(definition, source_command_id="command-1")
        trust = SkillEnvironmentTrust.trusted(
            revision.revision_hash,
            "e" * 64,
            successes=1,
            expected_cost=2,
            portable=True,
        )

        await store.save_revision(definition, revision)
        await store.record_validation(
            trust,
            policy_report={"valid": True},
            learning_evidence=("a" * 64,),
            validation_evidence=("b" * 64,),
        )
        revisions, trusts = await store.load_live_catalog(environment_fingerprint="e" * 64)

        assert revisions == {revision.revision_hash: revision}
        assert trusts == [trust]

        current = trust
        for index in range(3):
            current = await store.record_execution_outcome(
                execution_id=f"execution-{index}",
                trust=current,
                attribution=ExecutionAttribution.ATTRIBUTABLE_FAILURE,
                command_id=f"live-{index}",
                demotion_threshold=3,
            )
        _, after_demotion = await store.load_live_catalog(environment_fingerprint="e" * 64)
        assert after_demotion[0].status is TrustStatus.DEMOTED
        assert after_demotion[0].expected_cost == 2
        assert after_demotion[0].portable is True
    finally:
        await store.close()
