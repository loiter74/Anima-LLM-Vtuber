"""Environment-trusted immutable Skill IR selection without fallback."""

from __future__ import annotations

from typing import Any

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.skill.applicability import SkillApplicability
from animetta.tools.minecraft.skill.ir import (
    ActionStep,
    BranchStep,
    FailStep,
    GoalInputExpression,
    LiteralExpression,
    ObservationExpression,
    Predicate,
    RepeatStep,
    SkillRevision,
    StepOutputExpression,
)
from animetta.tools.minecraft.skill.selection import (
    SkillSelectionCandidate,
    SkillSelectionContext,
    select_applicable_skill,
)
from animetta.tools.minecraft.skill.trust import (
    SkillEnvironmentTrust,
    stable_environment_fingerprint,
)

from ..budget import BudgetUsage
from ..goal_models import GoalSpec
from .base import Complete, ExecuteStep, StrategyDecision, StrategyFailure


class LiveStrategy:
    def __init__(
        self,
        *,
        revisions: dict[str, SkillRevision],
        applicabilities: dict[str, SkillApplicability],
        trusts: list[SkillEnvironmentTrust],
        manifest: RuntimeManifest,
        allow_skill_reuse: bool = True,
    ) -> None:
        self._revisions = revisions
        self._applicabilities = applicabilities
        self._trusts = trusts
        self._manifest = manifest
        self._allow_skill_reuse = allow_skill_reuse

    def prepare(self, goal: GoalSpec | None) -> dict:
        if goal is None:
            raise ValueError("live strategy requires a structured goal")
        return {
            "goal": goal,
            "revision": None,
            "frames": (),
            "bound_parameters": {},
            "selection_exclusions": (),
            "selection_pending": True,
            "outputs": {},
            "current_action": None,
            "pending_postconditions": (),
            "preconditions_checked": False,
        }

    @staticmethod
    def _path(value: object, path: str) -> object:
        current = value
        segments = tuple(filter(None, path.split(".")))
        for index, segment in enumerate(segments):
            if hasattr(current, segment):
                current = getattr(current, segment)
            elif isinstance(current, dict):
                candidates: tuple[str, ...] = (segment,)
                if index == 1 and segments[0] == "inventory":
                    candidates = (
                        segment,
                        segment.removeprefix("minecraft:"),
                        f"minecraft:{segment}" if ":" not in segment else segment,
                    )
                matching = next((key for key in candidates if key in current), None)
                current = current.get(matching) if matching is not None else None
            else:
                return None
        return current

    def _expression(
        self,
        expression: object,
        *,
        goal: GoalSpec,
        observation: Observation,
        outputs: dict[str, object],
        bindings: dict[str, object],
    ) -> Any:
        if isinstance(expression, LiteralExpression):
            return expression.value
        if isinstance(expression, GoalInputExpression):
            if expression.name in bindings:
                return bindings[expression.name]
            return {
                "target": goal.target,
                "quantity": goal.quantity,
                "count": goal.quantity,
            }.get(expression.name)
        if isinstance(expression, ObservationExpression):
            return self._path(observation, expression.path)
        if isinstance(expression, StepOutputExpression):
            return self._path(outputs.get(expression.step_id), expression.path)
        raise ValueError("unsupported Skill IR expression")

    def _predicate(
        self,
        predicate: Predicate,
        *,
        goal: GoalSpec,
        observation: Observation,
        outputs: dict[str, object],
        bindings: dict[str, object],
    ) -> bool:
        left = self._expression(
            predicate.left,
            goal=goal,
            observation=observation,
            outputs=outputs,
            bindings=bindings,
        )
        right = self._expression(
            predicate.right,
            goal=goal,
            observation=observation,
            outputs=outputs,
            bindings=bindings,
        )
        operations = {
            "eq": lambda: left == right,
            "ne": lambda: left != right,
            "lt": lambda: left < right,
            "lte": lambda: left <= right,
            "gt": lambda: left > right,
            "gte": lambda: left >= right,
            "contains": lambda: right in left,
        }
        try:
            return bool(operations[predicate.op]())
        except (KeyError, TypeError):
            return False

    def _resolve_parameters(
        self,
        step: ActionStep,
        *,
        goal: GoalSpec,
        observation: Observation,
        outputs: dict[str, object],
        bindings: dict[str, object],
    ) -> dict:
        return {
            name: self._expression(
                expression,
                goal=goal,
                observation=observation,
                outputs=outputs,
                bindings=bindings,
            )
            for name, expression in step.parameters.items()
        }

    def propose(self, state: dict, observation: Observation) -> StrategyDecision:
        if state.get("selection_pending"):
            self._select_revision(state, observation)
        revision = state["revision"]
        if revision is None:
            return StrategyFailure(
                code="NO_ELIGIBLE_SKILL",
                message="No trusted revision matches the current environment",
            )
        frames = [dict(frame) for frame in state["frames"]]
        goal = state["goal"]
        outputs = state["outputs"]
        bindings = state["bound_parameters"]
        if not state.get("preconditions_checked"):
            if not all(
                self._predicate(
                    predicate,
                    goal=goal,
                    observation=observation,
                    outputs=outputs,
                    bindings=bindings,
                )
                for predicate in revision.program.preconditions
            ):
                return StrategyFailure(
                    code="SKILL_PRECONDITION_FAILED",
                    message="Skill revision preconditions were not satisfied",
                )
            state["preconditions_checked"] = True
        pending = state.get("pending_postconditions", ())
        if pending and not all(
            self._predicate(
                predicate,
                goal=goal,
                observation=observation,
                outputs=outputs,
                bindings=bindings,
            )
            for predicate in pending
        ):
            return StrategyFailure(
                code="ACTION_POSTCONDITION_FAILED",
                message="Skill action postconditions were not satisfied",
            )
        state["pending_postconditions"] = ()
        while frames:
            frame = frames[-1]
            if frame["kind"] == "repeat":
                repeat = frame["step"]
                if frame["iteration"] >= repeat.max_iterations or (
                    repeat.condition is not None
                    and not self._predicate(
                        repeat.condition,
                        goal=goal,
                        observation=observation,
                        outputs=outputs,
                        bindings=bindings,
                    )
                ):
                    frames.pop()
                    continue
                frame["iteration"] += 1
                frames.append({"kind": "sequence", "steps": repeat.steps, "index": 0})
                continue

            if frame["index"] >= len(frame["steps"]):
                frames.pop()
                continue
            step = frame["steps"][frame["index"]]
            frame["index"] += 1
            if isinstance(step, FailStep):
                state["frames"] = tuple(frames)
                return StrategyFailure(code=step.code, message=step.message)
            if isinstance(step, BranchStep):
                branch = (
                    step.then_steps
                    if self._predicate(
                        step.condition,
                        goal=goal,
                        observation=observation,
                        outputs=outputs,
                        bindings=bindings,
                    )
                    else step.else_steps
                )
                frames.append({"kind": "sequence", "steps": branch, "index": 0})
                continue
            if isinstance(step, RepeatStep):
                frames.append({"kind": "repeat", "step": step, "iteration": 0})
                continue
            if isinstance(step, ActionStep):
                capability = self._manifest.capability(step.capability)
                maximum = capability.maximum_cost
                state["frames"] = tuple(frames)
                state["current_action"] = step.step_id
                state["pending_postconditions"] = step.postconditions
                return ExecuteStep(
                    capability=step.capability,
                    parameters=self._resolve_parameters(
                        step,
                        goal=goal,
                        observation=observation,
                        outputs=outputs,
                        bindings=bindings,
                    ),
                    maximum_cost=BudgetUsage(
                        max_actions=maximum.max_actions,
                        max_strategy_attempts=maximum.max_strategy_attempts,
                        max_travel_distance=maximum.max_travel_distance,
                        max_blocks_changed=maximum.max_blocks_changed,
                        max_damage_taken=maximum.max_damage_taken,
                        resource_consumption=maximum.resource_consumption,
                    ),
                )

        if not all(
            self._predicate(
                predicate,
                goal=goal,
                observation=observation,
                outputs=outputs,
                bindings=bindings,
            )
            for predicate in revision.program.postconditions
        ):
            return StrategyFailure(
                code="SKILL_POSTCONDITION_FAILED",
                message="Skill revision postconditions were not satisfied",
            )
        state["frames"] = ()
        return Complete(output={"revision_hash": revision.revision_hash})

    def _select_revision(self, state: dict, observation: Observation) -> None:
        environment = stable_environment_fingerprint(self._manifest.profile)
        trust_by_revision = {
            trust.revision_hash: trust
            for trust in self._trusts
            if trust.environment_fingerprint == environment
        }
        candidates = tuple(
            SkillSelectionCandidate(
                revision=revision,
                applicability=self._applicabilities[revision_hash],
                trust=trust_by_revision[revision_hash],
            )
            for revision_hash, revision in self._revisions.items()
            if revision_hash in self._applicabilities and revision_hash in trust_by_revision
        )
        constraints = state["goal"].constraints
        discovery_states = constraints.get("discovery_states", {})
        technology_nodes = constraints.get("technology_nodes", ())
        selection = select_applicable_skill(
            candidates,
            SkillSelectionContext(
                goal=state["goal"],
                environment_fingerprint=environment,
                available_capabilities=frozenset(
                    capability.name for capability in self._manifest.capabilities
                ),
                discovery_states=(discovery_states if isinstance(discovery_states, dict) else {}),
                technology_nodes=frozenset(
                    technology_nodes
                    if isinstance(technology_nodes, (list, tuple, set, frozenset))
                    else ()
                ),
                observation=observation.model_dump(mode="python"),
                allow_skill_reuse=self._allow_skill_reuse,
            ),
        )
        selected = (
            self._revisions.get(selection.selected_revision_hash)
            if selection.selected_revision_hash is not None
            else None
        )
        state["revision"] = selected
        state["frames"] = (
            ({"kind": "sequence", "steps": selected.program.steps, "index": 0},)
            if selected is not None
            else ()
        )
        state["bound_parameters"] = selection.bound_parameters
        state["selection_exclusions"] = selection.exclusions
        state["selection_pending"] = False

    def accept_result(self, state: dict, result: object) -> dict:
        outputs = dict(state["outputs"])
        current_action = state.get("current_action")
        if current_action is not None:
            outputs[current_action] = result
        return {**state, "outputs": outputs, "current_action": None}
