"""Bounded declarative Skill IR and its static validator/compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.voyager.budget import BudgetUsage, ExecutionBudget


class SkillIRValidationError(ValueError):
    """A program is schema-valid but unsafe or inconsistent with its manifest."""


class _IRModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ParameterSpec(_IRModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value_type: Literal["string", "integer", "number", "boolean"]
    required: bool = True
    default: str | int | float | bool | None = None


class LiteralExpression(_IRModel):
    kind: Literal["literal"]
    value: str | int | float | bool | None


class GoalInputExpression(_IRModel):
    kind: Literal["goal_input"]
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class ObservationExpression(_IRModel):
    kind: Literal["observation"]
    path: str = Field(min_length=1, max_length=256)


class StepOutputExpression(_IRModel):
    kind: Literal["step_output"]
    step_id: str = Field(min_length=1, max_length=128)
    path: str = Field(default="", max_length=256)


Expression = Annotated[
    LiteralExpression | GoalInputExpression | ObservationExpression | StepOutputExpression,
    Field(discriminator="kind"),
]


class Predicate(_IRModel):
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains"]
    left: Expression
    right: Expression


class ActionStep(_IRModel):
    kind: Literal["action"]
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,127}$")
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parameters: dict[str, Expression]
    postconditions: tuple[Predicate, ...] = ()


class FailStep(_IRModel):
    kind: Literal["fail"]
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,127}$")
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    message: str = ""


LeafStep = Annotated[ActionStep | FailStep, Field(discriminator="kind")]


class BranchStep(_IRModel):
    kind: Literal["branch"]
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,127}$")
    condition: Predicate
    then_steps: tuple[LeafStep, ...]
    else_steps: tuple[LeafStep, ...]


class RepeatStep(_IRModel):
    kind: Literal["repeat"]
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,127}$")
    max_iterations: int = Field(gt=0, le=32)
    condition: Predicate | None = None
    steps: tuple[LeafStep, ...]


SkillStep = Annotated[
    ActionStep | BranchStep | RepeatStep | FailStep,
    Field(discriminator="kind"),
]


class PortabilityDeclaration(_IRModel):
    portable: bool = False
    dimensions: tuple[str, ...] = ()
    notes: str = Field(default="", max_length=500)


class SkillProgram(_IRModel):
    schema_version: Literal["1"] = "1"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    parameters: tuple[ParameterSpec, ...] = ()
    preconditions: tuple[Predicate, ...] = ()
    steps: tuple[SkillStep, ...] = Field(min_length=1, max_length=128)
    postconditions: tuple[Predicate, ...] = Field(min_length=1)
    portability: PortabilityDeclaration = PortabilityDeclaration()

    @property
    def canonical_hash(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class SkillDefinition(_IRModel):
    definition_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(max_length=1000)


class SkillRevision(_IRModel):
    definition_id: str
    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_revision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    program: SkillProgram
    static_cost: BudgetUsage
    source_command_id: str


@dataclass(frozen=True)
class CompiledSkillProgram:
    program: SkillProgram
    static_cost: BudgetUsage

    def to_revision(
        self,
        definition: SkillDefinition,
        *,
        source_command_id: str,
        parent_revision_hash: str | None = None,
    ) -> SkillRevision:
        return SkillRevision(
            definition_id=definition.definition_id,
            revision_hash=self.program.canonical_hash,
            parent_revision_hash=parent_revision_hash,
            program=self.program,
            static_cost=self.static_cost,
            source_command_id=source_command_id,
        )


_OBSERVATION_TYPES = {
    "position.x": "number",
    "position.y": "number",
    "position.z": "number",
    "health": "number",
    "food": "integer",
    "environment.dimension": "string",
    "environment.biome": "string",
}


def _observation_type(path: str) -> str:
    if path.startswith("inventory.") or path.startswith("equipment."):
        return "integer" if path.startswith("inventory.") else "string"
    try:
        return _OBSERVATION_TYPES[path]
    except KeyError as exc:
        raise SkillIRValidationError(f"forbidden observation field: {path}") from exc


def _literal_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "null"


def _expression_type(
    expression: Expression,
    *,
    parameters: dict[str, ParameterSpec],
    prior_steps: set[str],
) -> str:
    if isinstance(expression, LiteralExpression):
        return _literal_type(expression.value)
    if isinstance(expression, GoalInputExpression):
        if expression.name not in parameters:
            raise SkillIRValidationError(f"unbound goal input: {expression.name}")
        return parameters[expression.name].value_type
    if isinstance(expression, ObservationExpression):
        return _observation_type(expression.path)
    if expression.step_id not in prior_steps:
        raise SkillIRValidationError(f"unbound step output: {expression.step_id}")
    return "unknown"


def _validate_predicate(
    predicate: Predicate,
    *,
    parameters: dict[str, ParameterSpec],
    prior_steps: set[str],
) -> None:
    _expression_type(predicate.left, parameters=parameters, prior_steps=prior_steps)
    _expression_type(predicate.right, parameters=parameters, prior_steps=prior_steps)


def _add_cost(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
    return left.plus(right)


def _scale_cost(cost: BudgetUsage, factor: int) -> BudgetUsage:
    return BudgetUsage(
        max_actions=cost.max_actions * factor,
        max_strategy_attempts=cost.max_strategy_attempts * factor,
        max_travel_distance=cost.max_travel_distance * factor,
        max_blocks_changed=cost.max_blocks_changed * factor,
        max_damage_taken=cost.max_damage_taken * factor,
        resource_consumption={k: v * factor for k, v in cost.resource_consumption.items()},
    )


def _max_cost(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
    keys = set(left.resource_consumption) | set(right.resource_consumption)
    return BudgetUsage(
        max_actions=max(left.max_actions, right.max_actions),
        max_strategy_attempts=max(left.max_strategy_attempts, right.max_strategy_attempts),
        max_travel_distance=max(left.max_travel_distance, right.max_travel_distance),
        max_blocks_changed=max(left.max_blocks_changed, right.max_blocks_changed),
        max_damage_taken=max(left.max_damage_taken, right.max_damage_taken),
        resource_consumption={
            key: max(left.resource_consumption.get(key, 0), right.resource_consumption.get(key, 0))
            for key in keys
        },
    )


def _validate_action(
    step: ActionStep,
    *,
    capabilities: dict[str, dict[str, Any]],
    parameters: dict[str, ParameterSpec],
    prior_steps: set[str],
) -> BudgetUsage:
    descriptor = capabilities.get(step.capability)
    if descriptor is None:
        raise SkillIRValidationError(f"unknown capability: {step.capability}")
    schema = descriptor.get("parameters_schema", {})
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = required - set(step.parameters)
    if missing:
        raise SkillIRValidationError(f"missing capability parameters: {sorted(missing)}")
    if schema.get("additionalProperties") is False:
        extra = set(step.parameters) - set(properties)
        if extra:
            raise SkillIRValidationError(f"unknown capability parameters: {sorted(extra)}")
    for name, expression in step.parameters.items():
        actual = _expression_type(expression, parameters=parameters, prior_steps=prior_steps)
        expected = properties.get(name, {}).get("type")
        compatible = actual == expected or (actual == "integer" and expected == "number")
        if expected and actual != "unknown" and not compatible:
            raise SkillIRValidationError(
                f"capability parameter {name} expects {expected}, got {actual}"
            )
    for predicate in step.postconditions:
        _validate_predicate(predicate, parameters=parameters, prior_steps=prior_steps)
    cost = descriptor.get("maximum_cost", BudgetUsage())
    return cost if isinstance(cost, BudgetUsage) else BudgetUsage.model_validate(cost)


def _cost_fits(cost: BudgetUsage, budget: ExecutionBudget) -> bool:
    scalar_fields = (
        "max_actions",
        "max_strategy_attempts",
        "max_travel_distance",
        "max_blocks_changed",
        "max_damage_taken",
    )
    if any(getattr(cost, field) > getattr(budget, field) for field in scalar_fields):
        return False
    return all(
        amount <= budget.resource_consumption.get(name, 0)
        for name, amount in cost.resource_consumption.items()
    )


def compile_skill_program(
    program: SkillProgram,
    *,
    capabilities: dict[str, dict[str, Any]],
    budget: ExecutionBudget,
) -> CompiledSkillProgram:
    """Validate dataflow/capabilities and compute a conservative static bound."""

    parameter_map = {parameter.name: parameter for parameter in program.parameters}
    if len(parameter_map) != len(program.parameters):
        raise SkillIRValidationError("duplicate skill parameter")
    seen_steps: set[str] = set()
    total = BudgetUsage()

    for predicate in program.preconditions:
        _validate_predicate(predicate, parameters=parameter_map, prior_steps=set())

    def leaf_cost(steps: tuple[LeafStep, ...], prior: set[str]) -> BudgetUsage:
        subtotal = BudgetUsage()
        for leaf in steps:
            if leaf.step_id in seen_steps:
                raise SkillIRValidationError(f"duplicate step id: {leaf.step_id}")
            if isinstance(leaf, ActionStep):
                subtotal = _add_cost(
                    subtotal,
                    _validate_action(
                        leaf,
                        capabilities=capabilities,
                        parameters=parameter_map,
                        prior_steps=prior,
                    ),
                )
            seen_steps.add(leaf.step_id)
            prior.add(leaf.step_id)
        return subtotal

    for step in program.steps:
        if step.step_id in seen_steps:
            raise SkillIRValidationError(f"duplicate step id: {step.step_id}")
        prior = set(seen_steps)
        if isinstance(step, ActionStep):
            total = _add_cost(
                total,
                _validate_action(
                    step,
                    capabilities=capabilities,
                    parameters=parameter_map,
                    prior_steps=prior,
                ),
            )
        elif isinstance(step, BranchStep):
            _validate_predicate(step.condition, parameters=parameter_map, prior_steps=prior)
            then_cost = leaf_cost(step.then_steps, set(prior))
            else_cost = leaf_cost(step.else_steps, set(prior))
            total = _add_cost(total, _max_cost(then_cost, else_cost))
        elif isinstance(step, RepeatStep):
            if step.condition:
                _validate_predicate(step.condition, parameters=parameter_map, prior_steps=prior)
            total = _add_cost(
                total,
                _scale_cost(leaf_cost(step.steps, set(prior)), step.max_iterations),
            )
        seen_steps.add(step.step_id)

    for predicate in program.postconditions:
        _validate_predicate(predicate, parameters=parameter_map, prior_steps=seen_steps)
    if not _cost_fits(total, budget):
        raise SkillIRValidationError("static cost exceeds parent command budget")
    return CompiledSkillProgram(program=program, static_cost=total)
