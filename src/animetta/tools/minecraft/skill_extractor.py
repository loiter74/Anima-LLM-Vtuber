"""
SkillExtractor - Extracts reusable Skills from successful task execution traces.

Uses LLM to analyze a TaskTrace and produce a structured Skill that captures
the reusable pattern for future execution.  Includes duplicate detection to
avoid storing near-identical skills that already have high success rates.

Usage:
    extractor = SkillExtractor(llm_service=llm, skill_library=library)
    skill = await extractor.extract(trace, context={"time": "day"})
    if skill:
        await library.save_skill(skill)
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from .skill_library import Skill, SkillLibrary, SkillStep

if TYPE_CHECKING:
    from .trace_recorder import TaskTrace


# ── Prompts ──────────────────────────────────────────────────────────────────

SKILL_EXTRACTION_SYSTEM_PROMPT = """\
You are a Minecraft skill extractor.  Given a successful task execution trace,
produce a reusable Skill definition as JSON.

A Skill is a named, parameterised sequence of atomic steps (goto, collect, mine,
place, craft, chat, check, wait) that can be re-executed in similar situations.

Output ONLY valid JSON — no markdown fences, no explanation.

JSON schema:
{
  "name": "short_snake_case_name",
  "description": "one-sentence description of what the skill does",
  "category": "collection|crafting|building|exploration|combat|survival",
  "parameters": {"param_name": "type_hint"},
  "preconditions": ["condition_string"],
  "postconditions": ["condition_string"],
  "tags": ["tag1", "tag2"],
  "steps": [
    {
      "name": "goto|collect|mine|place|craft|chat|check|wait",
      "params": {"key": "value"},
      "preconditions": [],
      "timeout": 60.0,
      "retry": 0
    }
  ]
}

Guidelines:
- name: concise snake_case, verb_noun pattern (e.g. collect_wood, craft_pickaxe)
- category: one of collection, crafting, building, exploration, combat, survival
- parameters: abstract over specific quantities/types (e.g. "count": "int", "block_type": "str")
- preconditions: inventory or world-state checks (e.g. "has_wood >= 4", "is_day")
- postconditions: what is true after the skill succeeds (e.g. "has_crafting_table")
- tags: free-form keywords for search
- steps: use only the step types listed above
- step params should use concrete values from the trace, not parameter names
- If the trace shows gathering before crafting, keep that order
- Limit to essential steps — skip idling, redundant movements, or failed attempts

Below are examples of correct skill extractions.
"""

# ── Few-shot examples ────────────────────────────────────────────────────────

_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    # 1. collect_wood
    {
        "user": """\
Trace:
  goal: "collect 10 oak logs"
  steps:
    1. goto {x:120, y:64, z:-340} → success (2.1s)
    2. collect {block_type:"oak_log", count:5} → success (18.3s)
    3. collect {block_type:"oak_log", count:5} → success (16.7s)
  result: success
  items_gained: {oak_log: 10}
  duration: 37.1s""",
        "assistant": json.dumps({
            "name": "collect_wood",
            "description": "Gather oak logs by navigating to nearby trees and mining them.",
            "category": "collection",
            "parameters": {"count": "int", "block_type": "str"},
            "preconditions": [],
            "postconditions": ["has_oak_log >= count"],
            "tags": ["wood", "gathering", "oak", "logs", "resources"],
            "steps": [
                {"name": "collect", "params": {"block_type": "oak_log", "count": 5},
                 "preconditions": [], "timeout": 60.0, "retry": 1},
                {"name": "collect", "params": {"block_type": "oak_log", "count": 5},
                 "preconditions": [], "timeout": 60.0, "retry": 1},
            ],
        }),
    },
    # 2. craft_tool
    {
        "user": """\
Trace:
  goal: "craft a wooden pickaxe"
  steps:
    1. collect {block_type:"oak_log", count:3} → success (12.5s)
    2. craft {recipe:"oak_planks", count:12} → success (0.3s)
    3. craft {recipe:"sticks", count:4} → success (0.2s)
    4. craft {recipe:"wooden_pickaxe", count:1} → success (0.3s)
  result: success
  items_gained: {wooden_pickaxe: 1, oak_planks: 8}
  duration: 13.3s""",
        "assistant": json.dumps({
            "name": "craft_wooden_pickaxe",
            "description": "Craft a wooden pickaxe from oak logs: logs → planks → sticks → pickaxe.",
            "category": "crafting",
            "parameters": {},
            "preconditions": ["has_oak_log >= 3"],
            "postconditions": ["has_wooden_pickaxe >= 1"],
            "tags": ["crafting", "pickaxe", "wooden", "tool", "mining"],
            "steps": [
                {"name": "craft", "params": {"recipe": "oak_planks", "count": 12},
                 "preconditions": [], "timeout": 10.0, "retry": 0},
                {"name": "craft", "params": {"recipe": "sticks", "count": 4},
                 "preconditions": [], "timeout": 10.0, "retry": 0},
                {"name": "craft", "params": {"recipe": "wooden_pickaxe", "count": 1},
                 "preconditions": [], "timeout": 10.0, "retry": 0},
            ],
        }),
    },
    # 3. build_platform
    {
        "user": """\
Trace:
  goal: "build a 3x3 platform at spawn"
  steps:
    1. goto {x:0, y:64, z:0} → success (3.2s)
    2. place {block_type:"cobblestone", x:-1, y:63, z:-1} → success (0.5s)
    3. place {block_type:"cobblestone", x:0, y:63, z:-1} → success (0.4s)
    4. place {block_type:"cobblestone", x:1, y:63, z:-1} → success (0.5s)
    5. place {block_type:"cobblestone", x:-1, y:63, z:0} → success (0.4s)
    6. place {block_type:"cobblestone", x:0, y:63, z:0} → success (0.4s)
    7. place {block_type:"cobblestone", x:1, y:63, z:0} → success (0.4s)
    8. place {block_type:"cobblestone", x:-1, y:63, z:1} → success (0.5s)
    9. place {block_type:"cobblestone", x:0, y:63, z:1} → success (0.4s)
    10. place {block_type:"cobblestone", x:1, y:63, z:1} → success (0.5s)
  result: success
  items_gained: {}
  items_lost: {cobblestone: 9}
  duration: 7.2s""",
        "assistant": json.dumps({
            "name": "build_platform",
            "description": "Build a 3x3 cobblestone platform centred at the given coordinates.",
            "category": "building",
            "parameters": {"center_x": "int", "center_y": "int", "center_z": "int",
                           "block_type": "str"},
            "preconditions": ["has_cobblestone >= 9"],
            "postconditions": [],
            "tags": ["building", "platform", "base", "cobblestone"],
            "steps": [
                {"name": "goto", "params": {"x": 0, "y": 64, "z": 0},
                 "preconditions": [], "timeout": 30.0, "retry": 0},
                {"name": "place", "params": {"block_type": "cobblestone", "x": -1, "y": 63, "z": -1},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": 0, "y": 63, "z": -1},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": 1, "y": 63, "z": -1},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": -1, "y": 63, "z": 0},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": 0, "y": 63, "z": 0},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": 1, "y": 63, "z": 0},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": -1, "y": 63, "z": 1},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": 0, "y": 63, "z": 1},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
                {"name": "place", "params": {"block_type": "cobblestone", "x": 1, "y": 63, "z": 1},
                 "preconditions": [], "timeout": 10.0, "retry": 1},
            ],
        }),
    },
    # 4. find_cave
    {
        "user": """\
Trace:
  goal: "find a cave entrance"
  steps:
    1. goto {x:150, y:64, z:-200} → success (4.5s)
    2. mine {block_type:"stone", count:3} → success (2.1s)
    3. goto {x:152, y:62, z:-198} → success (1.3s)
    4. mine {block_type:"stone", count:5} → success (3.4s)
    5. goto {x:155, y:58, z:-196} → success (2.0s)
  result: success
  items_gained: {cobblestone: 8}
  distance_traveled: 45.2
  duration: 13.3s""",
        "assistant": json.dumps({
            "name": "find_cave",
            "description": "Explore underground by mining stone blocks downward to locate a cave.",
            "category": "exploration",
            "parameters": {},
            "preconditions": ["has_pickaxe >= 1"],
            "postconditions": [],
            "tags": ["exploration", "cave", "underground", "mining"],
            "steps": [
                {"name": "mine", "params": {"block_type": "stone", "count": 3},
                 "preconditions": [], "timeout": 30.0, "retry": 1},
                {"name": "mine", "params": {"block_type": "stone", "count": 5},
                 "preconditions": [], "timeout": 30.0, "retry": 1},
            ],
        }),
    },
]

# Build the full system prompt with embedded few-shot examples
_FULL_SYSTEM_PROMPT: str = SKILL_EXTRACTION_SYSTEM_PROMPT + "".join(
    f"\nUser:\n{_ex['user']}\n\nAssistant:\n{_ex['assistant']}\n"
    for _ex in _FEW_SHOT_EXAMPLES
)


# ── User prompt template ─────────────────────────────────────────────────────

SKILL_EXTRACTION_USER_PROMPT = """\
Extract a reusable Skill from the following successful task trace.

Trace:
  goal: "{goal}"
  steps:
{steps_str}
  result: {result}
  items_gained: {items_gained}
  items_lost: {items_lost}
  distance_traveled: {distance_traveled}
  duration: {duration}s

Context:
{context_str}

Output the Skill JSON:"""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_trace_steps(steps: list[Any]) -> str:
    """Format ActionTrace steps into a numbered list for the prompt."""
    lines: list[str] = []
    for i, step in enumerate(steps):
        action = step.action
        params = step.params
        error = step.error
        dur = step.duration
        status = "error" if error else "success"
        lines.append(
            f"    {i + 1}. {action} {params} → {status} ({dur:.1f}s)"
        )
    return "\n".join(lines)


def _format_context(context: dict[str, Any] | None) -> str:
    """Format context dict into a readable block for the prompt."""
    if not context:
        return "  (none)"
    parts: list[str] = []
    for key, value in context.items():
        parts.append(f"  {key}: {value}")
    return "\n".join(parts)


# ── SkillExtractor ───────────────────────────────────────────────────────────


class SkillExtractorError(Exception):
    """Raised when skill extraction fails."""


class SkillExtractor:
    """Extracts reusable Skills from successful TaskTraces using LLM.

    Args:
        llm_service: An LLM service with an async ``.chat(messages=...)`` method
            that returns an object with a ``.content`` attribute.
        skill_library: Used for duplicate detection before saving.
        similarity_threshold: If a searched skill has ``success_rate`` above this
            value, the extraction is skipped (duplicate).
    """

    def __init__(
        self,
        llm_service: Any = None,
        skill_library: SkillLibrary | None = None,
        *,
        similarity_threshold: float = 0.8,
    ):
        self._llm = llm_service
        self._library = skill_library
        self._similarity_threshold = similarity_threshold

        logger.info(
            "[SkillExtractor] Initialized "
            f"(threshold={similarity_threshold})"
        )

    # ── Public API ───────────────────────────────────────────────────────

    def set_llm(self, llm_service: Any) -> None:
        """Set or update the LLM service."""
        self._llm = llm_service

    async def extract(
        self,
        trace: TaskTrace,
        context: dict[str, Any] | None = None,
    ) -> Skill | None:
        """Extract a reusable Skill from a successful TaskTrace.

        Args:
            trace: A completed ``TaskTrace`` (should have ``final_result == "success"``).
            context: Optional context (time of day, biome, inventory snapshot, etc.)

        Returns:
            A ``Skill`` instance if extraction succeeds and no high-confidence
            duplicate exists, otherwise ``None``.
        """
        if not self._llm:
            logger.error("[SkillExtractor] No LLM service configured")
            raise SkillExtractorError("No LLM service configured")

        if trace.final_result != "success":
            logger.warning(
                f"[SkillExtractor] Skipping non-successful trace: "
                f"'{trace.goal}' → {trace.final_result}"
            )
            return None

        if not trace.steps:
            logger.warning(
                f"[SkillExtractor] Skipping empty trace: '{trace.goal}'"
            )
            return None

        # ── 1. Duplicate detection ───────────────────────────────────────
        if self._library:
            is_dup, existing = await self._check_duplicate(trace.goal)
            if is_dup and existing is not None:
                logger.info(
                    f"[SkillExtractor] Duplicate detected for '{trace.goal}': "
                    f"existing skill '{existing.name}' "
                    f"(success_rate={existing.success_rate:.0%}) — skipping"
                )
                return None

        # ── 2. Build prompt ──────────────────────────────────────────────
        user_prompt = self._build_user_prompt(trace, context)

        messages = [
            {"role": "system", "content": _FULL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # ── 3. Call LLM ──────────────────────────────────────────────────
        logger.info(
            f"[SkillExtractor] Extracting skill from trace '{trace.goal}' "
            f"({len(trace.steps)} steps, {trace.total_duration:.1f}s)"
        )

        try:
            response = await self._llm.chat(messages=messages)
            raw_content = response.content
        except Exception as exc:
            logger.error(
                f"[SkillExtractor] LLM call failed: {type(exc).__name__}: {exc}"
            )
            raise SkillExtractorError(f"LLM call failed: {exc}") from exc

        # ── 4. Parse response ────────────────────────────────────────────
        try:
            skill_data = self._extract_json(raw_content)
        except json.JSONDecodeError as exc:
            logger.error(
                f"[SkillExtractor] Failed to parse LLM response as JSON: {exc}\n"
                f"Raw response (first 500 chars): {raw_content[:500]}"
            )
            raise SkillExtractorError(
                f"Failed to parse LLM response as JSON: {exc}"
            ) from exc

        # ── 5. Build Skill object ────────────────────────────────────────
        try:
            skill = self._build_skill(skill_data, trace)
        except (KeyError, ValueError) as exc:
            logger.error(
                f"[SkillExtractor] Invalid skill data from LLM: {exc}"
            )
            raise SkillExtractorError(
                f"Invalid skill data from LLM: {exc}"
            ) from exc

        logger.info(
            f"[SkillExtractor] Extracted skill '{skill.name}' "
            f"(category={skill.category}, steps={len(skill.steps)}, "
            f"tags={skill.tags})"
        )

        return skill

    # ── Duplicate detection ──────────────────────────────────────────────

    async def _check_duplicate(
        self, goal: str
    ) -> tuple[bool, Skill | None]:
        """Check if a similar high-confidence skill already exists.

        Uses ``skill_library.search_skills()`` with the goal text and
        returns ``(True, existing_skill)`` if a match is found whose
        ``success_rate >= similarity_threshold``.
        """
        if self._library is None:
            return False, None

        candidates = await self._library.search_skills(goal, limit=5)

        for skill in candidates:
            if skill.success_rate >= self._similarity_threshold:
                return True, skill

        return False, None

    # ── Prompt construction ──────────────────────────────────────────────

    def _build_user_prompt(
        self,
        trace: TaskTrace,
        context: dict[str, Any] | None,
    ) -> str:
        """Build the user prompt from a TaskTrace."""
        return SKILL_EXTRACTION_USER_PROMPT.format(
            goal=trace.goal,
            steps_str=_format_trace_steps(trace.steps),
            result=trace.final_result,
            items_gained=trace.items_gained,
            items_lost=trace.items_lost,
            distance_traveled=trace.distance_traveled,
            duration=f"{trace.total_duration:.1f}",
            context_str=_format_context(context),
        )

    # ── JSON extraction ──────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extract JSON from LLM response, handling markdown code blocks.

        Mirrors the pattern in :class:`MinecraftPlanner._extract_json`.
        """
        text = text.strip()

        # Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract from ```json ... ``` block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return json.loads(text[start:end].strip())

        # Extract from ``` ... ``` block (no language tag)
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            return json.loads(text[start:end].strip())

        raise json.JSONDecodeError("No valid JSON found in LLM response", text, 0)

    # ── Skill construction ───────────────────────────────────────────────

    @staticmethod
    def _build_skill(
        data: dict[str, Any],
        trace: TaskTrace,
    ) -> Skill:
        """Build a ``Skill`` from parsed JSON data and the source trace."""
        # Parse steps
        raw_steps: list[dict[str, Any]] = data.get("steps", [])
        steps: list[SkillStep] = []
        for raw in raw_steps:
            step = SkillStep(
                name=raw.get("name", "goto"),
                params=raw.get("params", {}),
                preconditions=raw.get("preconditions", []),
                timeout=float(raw.get("timeout", 60.0)),
                retry=int(raw.get("retry", 0)),
            )
            errors = step.validate_params()
            if errors:
                logger.warning(
                    f"[SkillExtractor] Step validation warnings: {errors}"
                )
            steps.append(step)

        if not steps:
            raise ValueError("Skill has no steps")

        # Build skill
        skill = Skill(
            id=uuid.uuid4().hex[:12],
            name=data.get("name", f"skill_{trace.id}"),
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            preconditions=data.get("preconditions", []),
            steps=steps,
            category=data.get("category", ""),
            postconditions=data.get("postconditions", []),
            tags=data.get("tags", []),
        )

        # Seed stats from the source trace — 1 success, 0 failures
        skill.success_count = 1
        skill.fail_count = 0
        skill.avg_duration = trace.total_duration
        skill.last_used = trace.timestamp

        return skill
