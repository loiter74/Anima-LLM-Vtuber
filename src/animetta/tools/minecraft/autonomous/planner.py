"""
LLM Planner — decomposes natural language goals into executable sub-task plans.

Uses Anima's existing LLM service to plan Minecraft bot behaviors.
Outputs structured JSON plans that the Node.js state machine can execute.
"""
import json
from dataclasses import dataclass, field

from loguru import logger

from ..skill.library import SkillLibrary

# ── Data models ──

@dataclass
class PlanStep:
    action: str           # goto | smart_goto | collect | mine | place | smart_build | chat | attack
    params: dict = field(default_factory=dict)
    description: str = ""

@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "pending"  # pending | running | complete | failed


# ── Tool catalog (what the bot can do) ──

AVAILABLE_TOOLS = [
    {"action": "goto",           "params": {"x": "int", "y": "int", "z": "int"},
     "desc": "Navigate to coordinates using A* pathfinding"},
    {"action": "smart_goto",     "params": {"target": "string (block type or entity name)"},
     "desc": "Smart navigate to nearest block/entity of given type (e.g. 'oak_tree', 'cow')"},
    {"action": "mine",           "params": {"block_type": "string", "count": "int"},
     "desc": "Find and mine nearest blocks within 10 blocks"},
    {"action": "collect",        "params": {"block_type": "string", "count": "int"},
     "desc": "Find, navigate to, mine, and collect blocks. More reliable than mine alone."},
    {"action": "place",          "params": {"block_type": "string", "x": "int", "y": "int", "z": "int"},
     "desc": "Place a block at specific coordinates (need solid block below)"},
    {"action": "smart_build",    "params": {"block_type": "string", "x": "int", "y": "int", "z": "int",
                                             "blueprint": "string (platform|wall|tower)"},
     "desc": "Multi-step building at a location. blueprints: platform(3x3), wall, tower"},
    {"action": "attack",         "params": {"target": "string (nearest_hostile | entity_name)"},
     "desc": "Fight nearest hostile mob or specific entity"},
    {"action": "chat",           "params": {"message": "string"},
     "desc": "Send a chat message to all players"},
]

TOOLS_DESC = "\n".join([
    f"- {t['action']}({t['params']}): {t['desc']}" for t in AVAILABLE_TOOLS
])


# ── Planner Prompt Template ──

PLANNER_SYSTEM_PROMPT = """You are a Minecraft bot planner. Your job is to decompose a natural language goal into a sequence of executable actions.

Available tools:
{tools_desc}

Rules:
1. Output ONLY valid JSON, no markdown, no explanation
2. Each step must use one of the available tools with correct parameters
3. Steps should be ordered logically (e.g., collect materials before building)
4. Include safety: if goal involves outdoor activity, consider time of day
5. If the goal is unclear, break it down into the most reasonable interpretation
6. Maximum 10 steps per plan

Format:
{{
  "goal": "original goal description",
  "reasoning": "brief 1-2 sentence reasoning",
  "steps": [
    {{"action": "collect", "params": {{"block_type": "oak_log", "count": 16}}, "description": "Collect 16 oak logs"}},
    ...
  ]
}}
"""

# ── Planner Class ──

class PlannerError(Exception):
    pass


class MinecraftPlanner:
    """LLM-powered Minecraft task planner"""

    def __init__(self, llm_service=None, skill_library: SkillLibrary | None = None):
        self._llm = llm_service
        self._skill_library = skill_library
        self._last_plan: Plan | None = None

    def set_llm(self, llm_service):
        """Set or update the LLM service"""
        self._llm = llm_service

    async def plan(self, goal: str, context: dict | None = None) -> Plan:
        """
        Decompose a natural language goal into a Plan.

        Args:
            goal: Natural language goal (e.g. "在我旁边建个小房子")
            context: Optional context dict (current position, inventory, time, etc.)

        Returns:
            Plan with executable steps

        Raises:
            PlannerError: If LLM unavailable or plan generation fails
        """
        if not self._llm:
            raise PlannerError("No LLM service configured")

        # Try SkillLibrary first — skip LLM if a matching skill exists
        if self._skill_library:
            skills = await self._skill_library.search_skills(goal, limit=3)
            if skills:
                best_skill = skills[0]
                plan = Plan(
                    goal=goal,
                    steps=[PlanStep(action=s.name, params=s.params) for s in best_skill.steps],
                )
                self._last_plan = plan
                logger.info(
                    f"[MinecraftPlanner] SkillLibrary match: '{best_skill.name}' "
                    f"→ {len(plan.steps)} steps for '{goal}'"
                )
                return plan

        # Build context string
        ctx_str = ""
        if context:
            parts = []
            if "position" in context:
                p = context["position"]
                parts.append(f"current position: ({p.get('x',0)}, {p.get('y',0)}, {p.get('z',0)})")
            if "inventory" in context:
                inv = context["inventory"]
                if inv:
                    parts.append(f"inventory: {inv}")
                else:
                    parts.append("inventory: empty")
            if "time" in context:
                parts.append(f"time: {context['time']}")
            if "nearby_players" in context:
                parts.append(f"nearby players: {context['nearby_players']}")
            ctx_str = "\nContext:\n" + "\n".join(parts)

        user_prompt = f"Goal: {goal}{ctx_str}\n\nGenerate a plan JSON:"

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT.format(tools_desc=TOOLS_DESC)},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self._llm.chat(messages=messages)
            plan_json = self._extract_json(response.content)
            plan = self._parse_plan(goal, plan_json)
            self._validate_plan(plan)
            self._last_plan = plan
            logger.info(f"[MinecraftPlanner] Plan generated: {len(plan.steps)} steps for '{goal}'")
            return plan

        except json.JSONDecodeError as e:
            logger.error(f"[MinecraftPlanner] LLM returned invalid JSON: {e}")
            raise PlannerError(f"Failed to parse LLM plan: {e}")
        except Exception as e:
            logger.error(f"[MinecraftPlanner] Planning failed: {e}")
            raise PlannerError(f"Planning failed: {e}")

    async def replan(self, failed_step_index: int, error: str, context: dict | None = None) -> Plan:
        """
        Replan after a step fails. Preserves completed steps, re-plans the rest.

        Args:
            failed_step_index: Index of the step that failed
            error: Error message from the failed step
            context: Current bot state
        """
        if not self._last_plan:
            raise PlannerError("No previous plan to replan from")

        remaining_goal = f"Continue the plan '{self._last_plan.goal}' from step {failed_step_index + 1}. "
        remaining_goal += f"Previous steps completed successfully. Step {failed_step_index} failed: {error}"

        context = context or {}
        context["completed_steps"] = failed_step_index

        return await self.plan(remaining_goal, context)

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks"""
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from code block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return json.loads(text[start:end].strip())
        raise json.JSONDecodeError("No valid JSON found", text, 0)

    def _parse_plan(self, goal: str, raw: dict) -> Plan:
        steps = []
        for s in raw.get("steps", []):
            steps.append(PlanStep(
                action=s.get("action", "goto"),
                params=s.get("params", {}),
                description=s.get("description", ""),
            ))
        return Plan(goal=goal, steps=steps)

    def _validate_plan(self, plan: Plan):
        """Validate that plan steps use known tools"""
        valid_actions = {t["action"] for t in AVAILABLE_TOOLS}
        for i, step in enumerate(plan.steps):
            if step.action not in valid_actions:
                logger.warning(f"[MinecraftPlanner] Step {i}: unknown action '{step.action}', will be attempted anyway")
            # Ensure params is a dict
            if not isinstance(step.params, dict):
                step.params = {}

    @property
    def last_plan(self) -> Plan | None:
        return self._last_plan


# ── Mode Selector ──

class ModeSelector:
    """Decides whether to use planner or rule mode based on context"""

    def __init__(self, planner: MinecraftPlanner, skill_library: SkillLibrary | None = None):
        self._planner = planner
        # Inject skill_library into the planner if provided and not already set
        if skill_library is not None and planner._skill_library is None:
            planner._skill_library = skill_library
        self._has_goal = False
        self._goal: str | None = None

    def set_goal(self, goal: str | None):
        """Set a natural language goal, or None to clear"""
        self._goal = goal
        self._has_goal = bool(goal and goal.strip())

    async def select_mode(self, context: dict | None = None) -> dict:
        """
        Select execution mode and generate plan if needed.
        Returns: {"mode": "planner"|"rule", "plan": [...]|null}
        """
        if self._has_goal and self._goal:
            try:
                plan = await self._planner.plan(self._goal, context)
                return {
                    "mode": "planner",
                    "plan": [
                        {"action": s.action, "params": s.params}
                        for s in plan.steps
                    ]
                }
            except PlannerError as e:
                logger.warning(f"[ModeSelector] Planner failed: {e}, falling back to rule mode")
                return {"mode": "rule", "plan": None, "error": str(e)}
        return {"mode": "rule", "plan": None}
