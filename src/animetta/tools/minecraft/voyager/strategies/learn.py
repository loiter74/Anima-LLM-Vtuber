"""Finite learning strategy with independent learning and validation chains."""

from __future__ import annotations

from collections.abc import Callable

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.skill.independent_validation import (
    IndependentValidationEvidence,
    ValidationEvidenceChain,
    decide_independent_validation,
    goal_contract_hash,
    goal_postconditions,
)
from animetta.tools.minecraft.skill.ir import (
    SkillDefinition,
    SkillProgram,
    SkillRevision,
    compile_skill_program,
)

from ..budget import BudgetUsage, ExecutionBudget
from ..goal_models import GoalSpec
from .base import Complete, ExecuteStep, StrategyDecision, StrategyFailure


class LearnStrategy:
    def __init__(
        self,
        *,
        resolve_frontier: Callable[[GoalSpec], tuple[str, ...]],
        propose_node: Callable[[str], dict],
        max_frontier_nodes: int,
        max_attempts: int,
        manifest: RuntimeManifest | None = None,
        compilation_budget: ExecutionBudget | None = None,
        source_command_id: str = "learning-command",
        build_program: Callable[[str, dict], SkillProgram] | None = None,
    ) -> None:
        if max_frontier_nodes < 1 or max_attempts < 1:
            raise ValueError("learn bounds must be positive")
        self._resolve_frontier = resolve_frontier
        self._propose_node = propose_node
        self._max_frontier_nodes = max_frontier_nodes
        self._max_attempts = max_attempts
        self._manifest = manifest
        self._compilation_budget = compilation_budget
        self._source_command_id = source_command_id
        self._build_program = build_program

    @staticmethod
    def _default_program(node: str, proposal: dict, goal: GoalSpec) -> SkillProgram:
        return SkillProgram.model_validate(
            {
                "name": f"learn_{node}".replace(":", "_").replace("-", "_"),
                "steps": [
                    {
                        "kind": "action",
                        "step_id": "execute",
                        "capability": proposal["capability"],
                        "parameters": {
                            name: {"kind": "literal", "value": value}
                            for name, value in proposal["parameters"].items()
                        },
                    }
                ],
                "postconditions": [
                    predicate.model_dump(mode="json") for predicate in goal_postconditions(goal)
                ],
            }
        )

    def _compile_candidate(self, node: str, proposal: dict, goal: GoalSpec) -> SkillRevision | None:
        if self._manifest is None or self._compilation_budget is None:
            return None
        program = (
            self._build_program(node, proposal)
            if self._build_program is not None
            else self._default_program(node, proposal, goal)
        )
        capabilities = {
            capability.name: {
                "parameters_schema": capability.parameters_schema,
                "maximum_cost": BudgetUsage(
                    max_actions=capability.maximum_cost.max_actions,
                    max_strategy_attempts=capability.maximum_cost.max_strategy_attempts,
                    max_travel_distance=capability.maximum_cost.max_travel_distance,
                    max_blocks_changed=capability.maximum_cost.max_blocks_changed,
                    max_damage_taken=capability.maximum_cost.max_damage_taken,
                    resource_consumption=capability.maximum_cost.resource_consumption,
                ),
            }
            for capability in self._manifest.capabilities
        }
        compiled = compile_skill_program(
            program, capabilities=capabilities, budget=self._compilation_budget
        )
        definition = SkillDefinition(
            definition_id=f"tech:{node}",
            name=program.name,
            description=f"Bounded learned candidate for technology node {node}",
        )
        return compiled.to_revision(definition, source_command_id=self._source_command_id)

    def prepare(self, goal: GoalSpec | None) -> dict:
        if goal is None:
            raise ValueError("learn strategy requires a structured goal")
        frontier = self._resolve_frontier(goal)[: self._max_frontier_nodes]
        if not frontier:
            return {"failure_code": "UNSUPPORTED_LEARNING_GOAL", "goal": goal}
        return {
            "goal": goal,
            "frontier": tuple(frontier),
            "node_index": 0,
            "attempt": 0,
            "phase": "learning",
            "learning_receipts": (),
            "validation_receipts": (),
            "trust_outcomes": (),
            "candidate_revisions": (),
            "learning_chains": (),
            "independent_validations": (),
            "active_proposal": None,
        }

    def propose(self, state: dict, observation: Observation) -> StrategyDecision:
        del observation
        if state.get("failure_code"):
            return StrategyFailure(
                code=state["failure_code"], message="Goal is outside the technology graph"
            )
        if state["node_index"] >= len(state["frontier"]):
            return Complete(
                output={
                    "nodes": state["frontier"],
                    "trust_outcomes": state["trust_outcomes"],
                    "candidate_revisions": state["candidate_revisions"],
                    "learning_evidence": state["learning_receipts"],
                    "validation_evidence": state["validation_receipts"],
                    "independent_validations": state["independent_validations"],
                }
            )
        if state["attempt"] >= self._max_attempts:
            return StrategyFailure(
                code="LEARNING_ATTEMPTS_EXHAUSTED",
                message="Bounded learning attempts were exhausted",
            )
        node = state["frontier"][state["node_index"]]
        proposal = state.get("active_proposal") or self._propose_node(node)
        return ExecuteStep(
            capability=proposal["capability"],
            parameters=proposal["parameters"],
            maximum_cost=proposal.get("maximum_cost", BudgetUsage(max_actions=1)),
        )

    def accept_result(self, state: dict, result: object) -> dict:
        data = result if isinstance(result, dict) else {}
        receipt_hash = data.get("receipt_hash")
        chain = self._evidence_chain(data)
        if state["phase"] == "learning":
            receipts = state["learning_receipts"] + ((receipt_hash,) if receipt_hash else ())
            node = state["frontier"][state["node_index"]]
            proposal = self._propose_node(node)
            revision = self._compile_candidate(node, proposal, state["goal"])
            return {
                **state,
                "phase": "validation",
                "attempt": state["attempt"] + 1,
                "learning_receipts": receipts,
                "learning_chains": state["learning_chains"]
                + ((chain,) if chain is not None else ()),
                "active_proposal": proposal,
                "candidate_revisions": state["candidate_revisions"]
                + ((revision,) if revision else ()),
            }
        receipts = state["validation_receipts"] + ((receipt_hash,) if receipt_hash else ())
        validations = state["independent_validations"]
        trust_outcome = "candidate_untrusted:MISSING_INDEPENDENT_EVIDENCE"
        revision = state["candidate_revisions"][-1] if state["candidate_revisions"] else None
        learning_chain = state["learning_chains"][-1] if state["learning_chains"] else None
        if revision is not None and learning_chain is not None and chain is not None:
            postcondition_hash = goal_contract_hash(revision.program.postconditions)
            evidence = IndependentValidationEvidence(
                validation_id=f"validation-{str(receipt_hash)[:24]}",
                revision_hash=revision.revision_hash,
                environment_fingerprint=state["goal"].constraints.get(
                    "environment_fingerprint", "0" * 64
                ),
                goal_contract_hash=postcondition_hash,
                learning=learning_chain,
                validation=chain,
                goal_verified=data.get("outcome") == "success",
            )
            validation_decision = decide_independent_validation(evidence)
            validations = (*validations, evidence)
            trust_outcome = (
                "environment_trusted"
                if validation_decision.trust_status == "trusted"
                else f"candidate_untrusted:{validation_decision.reason_code}"
            )
        return {
            **state,
            "phase": "learning",
            "node_index": state["node_index"] + 1,
            "attempt": 0,
            "validation_receipts": receipts,
            "trust_outcomes": state["trust_outcomes"] + (trust_outcome,),
            "independent_validations": validations,
            "active_proposal": None,
        }

    @staticmethod
    def _evidence_chain(data: dict) -> ValidationEvidenceChain | None:
        required = (
            "command_id",
            "correlation_id",
            "receipt_hash",
            "start_state_hash",
            "resource_instance_ref",
        )
        if any(not data.get(field) for field in required):
            return None
        return ValidationEvidenceChain(
            command_id=str(data["command_id"]),
            correlation_ids=(str(data["correlation_id"]),),
            receipt_refs=(f"receipt:{data['receipt_hash']}",),
            start_state_hash=str(data["start_state_hash"]),
            resource_instance_ref=str(data["resource_instance_ref"]),
        )
