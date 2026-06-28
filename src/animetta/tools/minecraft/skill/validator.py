"""
Skill Validator — validates extracted Skills before saving to the library.

Runs three categories of checks:
  1. Schema validation  — required fields (id, name, steps) and structural integrity
  2. Action validation  — every step action must be in AVAILABLE_TOOLS or STEP_TYPES
  3. Simulation         — dry-run through steps against a SimulatedState to catch
                          logical errors (missing items, impossible movements, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..autonomous.planner import AVAILABLE_TOOLS
from .library import STEP_TYPES, Skill, SkillStep

# ── Validation check names ────────────────────────────────────────────────────

CHECK_SCHEMA = "schema"
CHECK_ACTION = "action"
CHECK_SIMULATION = "simulation"

# Union of actions the bot can execute at runtime.
# AVAILABLE_TOOLS covers the Node.js side; STEP_TYPES covers the Python
# skill-library side.  Skills may reference either set.
VALID_ACTIONS: set[str] = {str(t["action"]) for t in AVAILABLE_TOOLS} | STEP_TYPES


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Outcome of validating a single Skill."""

    passed: bool
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "passed": self.passed,
            "checks": list(self.checks),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


# ── Simulated State ───────────────────────────────────────────────────────────


class SimulatedState:
    """Lightweight world state for dry-run skill simulation.

    Tracks inventory, position, health, and food so that
    :meth:`can_execute` can reason about whether a step is plausible
    without talking to a real Minecraft server.
    """

    def __init__(
        self,
        inventory: dict[str, int] | None = None,
        position: tuple[int, int, int] = (0, 64, 0),
        health: float = 20.0,
        food: int = 20,
    ) -> None:
        self.inventory: dict[str, int] = dict(inventory) if inventory else {}
        self.position: tuple[int, int, int] = position
        self.health: float = health
        self.food: int = food

    # ── queries ───────────────────────────────────────────────────────────

    def has_item(self, item: str, count: int = 1) -> bool:
        """Check whether the simulated inventory contains at least *count* of *item*."""
        return self.inventory.get(item, 0) >= count

    def can_execute(self, step: SkillStep) -> tuple[bool, str | None]:
        """Evaluate whether *step* is plausible given the current simulated state.

        Returns ``(True, None)`` when the step looks executable, or
        ``(False, reason)`` when a blocking issue is detected.
        """
        name = step.name
        params = step.params

        # Health gate — below 2 HP the bot is nearly dead
        if self.health < 2.0:
            return False, f"Health too low ({self.health:.1f}) to execute '{name}'"

        # Food gate — below 3 the bot can barely sprint
        if self.food < 3:
            return False, f"Food too low ({self.food}) to execute '{name}'"

        # Step-specific checks
        if name in ("craft",):
            recipe = params.get("recipe", "")
            if recipe and not self._can_craft(recipe):
                return (
                    False,
                    f"Cannot craft '{recipe}' — missing ingredients in simulated inventory",
                )

        if name == "place":
            block_type = params.get("block_type", "")
            if block_type and not self.has_item(block_type):
                return False, f"Cannot place '{block_type}' — not in simulated inventory"

        return True, None

    # ── state mutation ────────────────────────────────────────────────────

    def apply_step(self, step: SkillStep) -> None:
        """Mutate the simulated state to reflect a completed *step*.

        Best-effort: unknown step types are silently ignored so that
        simulation can continue through novel actions.
        """
        name = step.name
        params = step.params

        if name == "goto":
            self.position = (
                params.get("x", self.position[0]),
                params.get("y", self.position[1]),
                params.get("z", self.position[2]),
            )

        elif name in ("mine", "collect"):
            block_type = params.get("block_type", "")
            count = params.get("count", 1)
            if block_type:
                self.inventory[block_type] = self.inventory.get(block_type, 0) + count

        elif name == "place":
            block_type = params.get("block_type", "")
            count = params.get("count", 1)
            if block_type:
                current = self.inventory.get(block_type, 0)
                self.inventory[block_type] = max(0, current - count)

        elif name == "craft":
            # Optimistic: assume craft succeeds and adds recipe output
            recipe = params.get("recipe", "")
            if recipe:
                self.inventory[recipe] = self.inventory.get(recipe, 0) + params.get("count", 1)

        # chat, check, wait, attack, smart_goto, smart_build → no state change

    # ── internals ─────────────────────────────────────────────────────────

    def _can_craft(self, recipe: str) -> bool:
        """Heuristic check for craftability.

        A full recipe resolution engine is out of scope — this just checks
        that the inventory isn't completely empty (i.e. the bot has *some*
        materials to work with).
        """
        return len(self.inventory) > 0

    def snapshot(self) -> dict[str, Any]:
        """Return a plain dict snapshot for logging / debugging."""
        return {
            "position": list(self.position),
            "health": self.health,
            "food": self.food,
            "inventory": dict(self.inventory),
        }


# ── Validator ─────────────────────────────────────────────────────────────────


class SkillValidator:
    """Validates a :class:`Skill` before it is saved to the library.

    Three validation phases run sequentially; each phase adds its name to
    ``result.checks`` and may append to ``result.failures`` / ``result.warnings``.

    1. **Schema** — required fields present and non-empty.
    2. **Action** — every step action is in the known action vocabulary.
    3. **Simulation** — dry-run through steps with :class:`SimulatedState`.
    """

    def validate(
        self,
        skill: Skill,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate *skill* and return a :class:`ValidationResult`.

        Args:
            skill: The Skill to validate.
            context: Optional context dict used to initialise the
                :class:`SimulatedState`.  Recognised keys:

                - ``inventory`` — ``dict[str, int]``
                - ``position`` — ``tuple[int, int, int]``
                - ``health`` — ``float``
                - ``food`` — ``int``
        """
        result = ValidationResult(passed=True)
        ctx = context or {}

        # Phase 1: Schema
        self._check_schema(skill, result)

        # Phase 2: Action availability
        self._check_actions(skill, result)

        # Phase 3: Simulation (only if phases 1-2 didn't produce hard failures)
        if not result.failures:
            sim_state = self._build_sim_state(ctx)
            self._simulate(skill, sim_state, result)
        else:
            logger.warning(
                f"[SkillValidator] Skipping simulation for '{skill.id}' "
                f"due to {len(result.failures)} prior failure(s)"
            )

        result.passed = len(result.failures) == 0
        logger.info(
            f"[SkillValidator] Validation {'passed' if result.passed else 'FAILED'} "
            f"for skill '{skill.id}' — "
            f"checks={result.checks} failures={len(result.failures)} warnings={len(result.warnings)}"
        )
        return result

    # ── Phase 1: Schema ───────────────────────────────────────────────────

    def _check_schema(self, skill: Skill, result: ValidationResult) -> None:
        """Verify required fields and structural integrity."""
        result.checks.append(CHECK_SCHEMA)

        if not skill.id or not skill.id.strip():
            result.failures.append("Skill 'id' is missing or empty")

        if not skill.name or not skill.name.strip():
            result.failures.append("Skill 'name' is missing or empty")

        if not skill.steps:
            result.failures.append("Skill 'steps' is empty — at least one step is required")
            return  # No point checking step structure if there are no steps

        for idx, step in enumerate(skill.steps):
            if not isinstance(step, SkillStep):
                result.failures.append(
                    f"Step {idx} is not a SkillStep instance (got {type(step).__name__})"
                )
                continue

            if not step.name or not step.name.strip():
                result.failures.append(f"Step {idx} has empty 'name'")

            # Validate step params against STEP_TYPES definitions
            param_errors = step.validate_params()
            for err in param_errors:
                result.failures.append(f"Step {idx}: {err}")

        # Non-fatal schema warnings
        if not skill.description or not skill.description.strip():
            result.warnings.append(
                "Skill 'description' is empty — consider adding one for searchability"
            )

        if not skill.category:
            result.warnings.append("Skill 'category' is unset — categorisation aids retrieval")

    # ── Phase 2: Action availability ──────────────────────────────────────

    def _check_actions(self, skill: Skill, result: ValidationResult) -> None:
        """Ensure every step action is in the known action vocabulary."""
        result.checks.append(CHECK_ACTION)

        for idx, step in enumerate(skill.steps):
            if not isinstance(step, SkillStep):
                continue  # Already reported in schema check

            if step.name not in VALID_ACTIONS:
                result.failures.append(
                    f"Step {idx}: unknown action '{step.name}' — "
                    f"not in AVAILABLE_TOOLS or STEP_TYPES"
                )

    # ── Phase 3: Simulation ───────────────────────────────────────────────

    def _simulate(
        self,
        skill: Skill,
        state: SimulatedState,
        result: ValidationResult,
    ) -> None:
        """Dry-run through skill steps with a SimulatedState."""
        result.checks.append(CHECK_SIMULATION)

        logger.debug(
            f"[SkillValidator] Simulating skill '{skill.id}' "
            f"({len(skill.steps)} steps) from state {state.snapshot()}"
        )

        for idx, step in enumerate(skill.steps):
            if not isinstance(step, SkillStep):
                break  # Already reported; nothing to simulate

            can_run, reason = state.can_execute(step)
            if not can_run:
                result.failures.append(f"Simulation failed at step {idx} ({step.name}): {reason}")
                logger.warning(f"[SkillValidator] Simulation blocked at step {idx}: {reason}")
                return  # Hard stop — can't continue past a blocking failure

            # Apply the step to advance the simulated state
            state.apply_step(step)

            logger.debug(
                f"[SkillValidator] Step {idx} ({step.name}) simulated OK — "
                f"state now: pos={state.position} inv_items={len(state.inventory)}"
            )

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_sim_state(ctx: dict[str, Any]) -> SimulatedState:
        """Construct a :class:`SimulatedState` from a context dict."""
        pos_raw = ctx.get("position", (0, 64, 0))

        # Handle both dict {"x": ..., "y": ..., "z": ...} and tuple (x, y, z)
        if isinstance(pos_raw, dict):
            pos = (
                int(pos_raw.get("x", 0)),
                int(pos_raw.get("y", 64)),
                int(pos_raw.get("z", 0)),
            )
        else:
            pos = (int(pos_raw[0]), int(pos_raw[1]), int(pos_raw[2]))

        return SimulatedState(
            inventory=ctx.get("inventory", {}),
            position=pos,
            health=float(ctx.get("health", 20.0)),
            food=int(ctx.get("food", 20)),
        )
