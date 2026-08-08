from __future__ import annotations

import json
from pathlib import Path

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.skill import applicability as applicability_module
from animetta.tools.minecraft.skill.independent_validation import goal_contract_hash
from animetta.tools.minecraft.skill.revision_store import SkillRevisionStore
from animetta.tools.minecraft.skill.selection import (
    SkillSelectionCandidate,
    SkillSelectionContext,
    select_applicable_skill,
)
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint
from animetta.tools.minecraft.voyager.strategies.live import LiveStrategy

from .test_applicability_selection import _goal
from .test_independent_validation import _evidence, _module
from .test_skill_applicability import _applicability, _revision

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]


async def test_learned_acquisition_revision_is_reused_at_second_resource_instance(
    tmp_path,
) -> None:
    validation = _module()
    definition, revision = _revision()
    applicability = _applicability(
        applicability_module,
        revision.revision_hash,
    )
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    environment = stable_environment_fingerprint(manifest.profile)
    evidence = _evidence(
        validation,
        revision.revision_hash,
        environment_fingerprint=environment,
        goal_contract_hash=goal_contract_hash(revision.program.postconditions),
    )
    store = SkillRevisionStore(tmp_path / "skills.db")
    await store.connect()
    try:
        await store.save_revision(definition, revision)
        await store.save_applicability(applicability)
        trust = await store.record_independent_validation(
            evidence,
            policy_report={"valid": True},
            expected_cost=2,
            portable=False,
        )
        revisions, trusts = await store.load_live_catalog(environment_fingerprint=environment)
        loaded_applicability = await store.load_applicability(revision.revision_hash)
    finally:
        await store.close()

    assert loaded_applicability is not None
    second_resource_goal = _goal().model_copy(
        update={
            "constraints": {
                "discovery_states": {
                    "block:minecraft:copper_ore": "observed",
                },
                "technology_nodes": ["stone_tools"],
                "resource_instance_ref": "block:overworld:24:63:18",
            }
        }
    )
    selection = select_applicable_skill(
        (
            SkillSelectionCandidate(
                revision=revision,
                applicability=loaded_applicability,
                trust=trust,
            ),
        ),
        SkillSelectionContext(
            goal=second_resource_goal,
            environment_fingerprint=environment,
            available_capabilities=frozenset(
                capability.name for capability in manifest.capabilities
            ),
            discovery_states={"block:minecraft:copper_ore": "observed"},
            technology_nodes=frozenset({"stone_tools"}),
            observation=Observation.model_validate(MESSAGES["Observation"]).model_dump(
                mode="python"
            ),
            allow_skill_reuse=True,
        ),
    )
    live = LiveStrategy(
        revisions=revisions,
        applicabilities={revision.revision_hash: loaded_applicability},
        trusts=trusts,
        manifest=manifest,
    )
    state = live.prepare(second_resource_goal)
    action = live.propose(state, Observation.model_validate(MESSAGES["Observation"]))

    assert selection.selected_revision_hash == revision.revision_hash
    assert state["revision"].revision_hash == revision.revision_hash
    assert action.kind == "execute"
    assert action.parameters == {"block_type": "minecraft:raw_copper", "count": 2}
