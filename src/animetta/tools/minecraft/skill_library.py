"""
Skill Library - Voyager-style skill storage, retrieval, and composition

Skills are stored as atoms in Chroma (semantic search) with metadata in SQLite.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import aiosqlite

    from .bridge import MinecraftBridge

# Predefined step type constants
# Includes both Python-side step types and Node.js-side actions from AVAILABLE_TOOLS
STEP_TYPES: set[str] = {
    "goto", "smart_goto", "collect", "mine", "place", "smart_build",
    "craft", "chat", "check", "wait", "attack",
}

# Required parameters per step type: name -> (type, default)
# If default is not None, the param is optional (has a default value).
_STEP_PARAM_DEFS: dict[str, dict[str, tuple[type, Any]]] = {
    "goto":        {"x": (int, None), "y": (int, None), "z": (int, None)},
    "smart_goto":  {"target": (str, None)},
    "collect":     {"block_type": (str, None), "count": (int, 1)},
    "mine":        {"block_type": (str, None), "count": (int, 1)},
    "place":       {"block_type": (str, None), "x": (int, None), "y": (int, None), "z": (int, None)},
    "smart_build": {"block_type": (str, None), "x": (int, None), "y": (int, None), "z": (int, None), "blueprint": (str, None)},
    "craft":       {"recipe": (str, None), "count": (int, 1)},
    "chat":        {"message": (str, None)},
    "check":       {"condition": (str, None)},
    "wait":        {"seconds": (float, None)},
    "attack":      {"target": (str, None)},
}


@dataclass
class SkillStep:
    """A single executable step within a Skill."""
    name: str          # Step type, must be in STEP_TYPES
    params: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    timeout: float = 60.0
    retry: int = 0

    def validate_params(self) -> list[str]:
        """Validate params against the step type definition.

        Returns a list of error messages. Empty list means valid.
        """
        errors: list[str] = []

        if self.name not in STEP_TYPES:
            errors.append(f"Unknown step type '{self.name}', expected one of: {sorted(STEP_TYPES)}")
            return errors  # No point checking params for an unknown type

        defs = _STEP_PARAM_DEFS.get(self.name, {})

        # Check required params (no default)
        for param_name, (param_type, default) in defs.items():
            if param_name not in self.params:
                if default is None:
                    errors.append(f"Missing required param '{param_name}' for step type '{self.name}'")
            else:
                # Type check
                value = self.params[param_name]
                if not isinstance(value, param_type):
                    errors.append(
                        f"Param '{param_name}' for '{self.name}' must be {param_type.__name__}, "
                        f"got {type(value).__name__}: {value!r}"
                    )

        return errors

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "params": self.params,
            "preconditions": self.preconditions,
            "timeout": self.timeout,
            "retry": self.retry,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillStep:
        """Deserialize from a dict."""
        return cls(
            name=data["name"],
            params=data.get("params", {}),
            preconditions=data.get("preconditions", []),
            timeout=data.get("timeout", 60.0),
            retry=data.get("retry", 0),
        )


@dataclass
class Skill:
    """A reusable, composable Minecraft action skill."""
    id: str
    name: str
    description: str
    parameters: dict[str, str] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    body: dict[str, Any] = field(default_factory=dict)  # legacy — kept for backward compat
    steps: list[SkillStep] = field(default_factory=list)
    category: str = ""  # e.g. "survival", "collection", "building"
    postconditions: list[str] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    avg_duration: float = 0.0
    last_used: str = ""
    tags: list[str] = field(default_factory=list)
    is_learned: bool = False
    validated: bool = True

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "preconditions": self.preconditions,
            "body": self.body,
            "steps": [s.to_dict() for s in self.steps],
            "category": self.category,
            "postconditions": self.postconditions,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "tags": self.tags,
            "is_learned": self.is_learned,
            "validated": self.validated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        # Handle SkillStep deserialization from nested dicts
        steps_data = data.pop("steps", [])
        steps = [SkillStep.from_dict(s) for s in steps_data]
        return cls(steps=steps, **data)


@dataclass
class SkillResult:
    """Result of executing a Skill."""
    success: bool
    skill_id: str
    failed_at: int | None = None  # step index where failure occurred
    reason: str | None = None
    duration: float = 0.0
    context_updates: dict[str, Any] = field(default_factory=dict)


# ── Condition Parsing ────────────────────────────────────────────────────────

# Pattern: "key > 6", "key < 15", "key >= 10", "key <= 3", "key == 5", "key != 0"
_COND_PATTERN = re.compile(
    r"^\s*(\w+)\s*(>=|<=|!=|==|>|<)\s*(.+?)\s*$"
)


def check_preconditions(
    conditions: list[str], context: dict[str, Any] | None = None
) -> bool:
    """Check whether all preconditions are satisfied against *context*.

    Supported formats:
      - ``"health > 6"``          → ``context["health"] > 6``
      - ``"food < 15"``           → ``context["food"] < 15``
      - ``"is_day"``              → ``context.get("is_day", False) is True``
      - ``"has_pickaxe"``         → ``context.get("inventory", {}).get("pickaxe", 0) > 0``

    Returns ``True`` when **every** condition is met (AND semantics).
    An empty *conditions* list trivially passes.
    """
    if not conditions:
        return True

    ctx = context or {}

    for cond in conditions:
        if not _check_single(cond, ctx):
            logger.debug(f"[SkillLibrary] Precondition failed: {cond}")
            return False

    return True


def _check_single(cond: str, ctx: dict[str, Any]) -> bool:  # noqa: C901
    """Evaluate a single condition string against *ctx*."""
    match = _COND_PATTERN.match(cond)
    if match:
        key, op, raw_value = match.group(1), match.group(2), match.group(3)

        # Handle "has_X >= N" inventory quantity checks
        if key.startswith("has_"):
            item = key[4:]  # Remove "has_" prefix
            inventory = ctx.get("inventory", {})
            actual_count = inventory.get(item, 0)
            try:
                expected_count = float(raw_value)
                actual_num = float(actual_count)
            except (ValueError, TypeError):
                return False

            if op == ">":
                return actual_num > expected_count
            if op == "<":
                return actual_num < expected_count
            if op == ">=":
                return actual_num >= expected_count
            if op == "<=":
                return actual_num <= expected_count
            if op == "==":
                return actual_num == expected_count
            if op == "!=":
                return actual_num != expected_count
            return False

        # Standard operator comparison
        actual: Any = ctx.get(key)

        # Try numeric comparison
        try:
            expected_num = float(raw_value)
            if actual is None:
                return False
            actual_num = float(actual)
        except (ValueError, TypeError):
            # String / bool comparison
            expected_str: str = raw_value.strip().strip("'\"")
            if actual is None:
                return False
            if op == "==":
                return actual == expected_str
            if op == "!=":
                return actual != expected_str
            return False

        if op == ">":
            return actual_num > expected_num
        if op == "<":
            return actual_num < expected_num
        if op == ">=":
            return actual_num >= expected_num
        if op == "<=":
            return actual_num <= expected_num
        if op == "==":
            return actual_num == expected_num
        if op == "!=":
            return actual_num != expected_num
        return False

    # Boolean / inventory conditions (no operator)
    cond = cond.strip()

    # "has_X" → inventory check: ctx["inventory"]["X"] > 0
    if cond.startswith("has_"):
        item = cond[4:]
        inventory = ctx.get("inventory", {})
        count = inventory.get(item, 0)
        return count > 0

    # Plain boolean flag: ctx["flag"] must be truthy
    return bool(ctx.get(cond, False))


# ── Skill Execution ──────────────────────────────────────────────────────────

# Health threshold below which a skill is aborted after combat.
_CRITICAL_HEALTH: float = 4.0


async def _handle_threat(
    bridge: MinecraftBridge,
    ctx: dict[str, Any],
) -> tuple[bool, str | None]:
    """Attempt to neutralise the current threat.

    Sends an ``attack {target: "nearest_hostile"}`` command, then refreshes
    health via ``status``.  Returns ``(True, None)`` on success or
    ``(False, reason)`` when the bot is too injured or the attack failed.
    """
    logger.warning("[SkillLibrary] Threat detected — pausing skill to engage hostile")

    try:
        resp = await bridge.send_command(
            "attack", {"target": "nearest_hostile"}, timeout=15.0
        )
    except (TimeoutError, Exception) as exc:
        reason = f"Threat handling failed: {type(exc).__name__}: {exc}"
        logger.error(f"[SkillLibrary] {reason}")
        return False, reason

    if resp.get("status") != "success":
        reason = f"Attack command returned error: {resp.get('result', 'unknown')}"
        logger.error(f"[SkillLibrary] {reason}")
        return False, reason

    # Refresh health after combat
    try:
        status_resp = await bridge.send_command("status", {}, timeout=10.0)
        if status_resp.get("status") == "success":
            result = status_resp.get("result", {})
            if isinstance(result, dict):
                new_health = result.get("health", ctx.get("health", 20.0))
                ctx["health"] = new_health
                if new_health < _CRITICAL_HEALTH:
                    reason = (
                        f"Health too low after combat ({new_health:.1f} < "
                        f"{_CRITICAL_HEALTH:.1f}) — aborting skill"
                    )
                    logger.error(f"[SkillLibrary] {reason}")
                    return False, reason
    except Exception:
        # Non-fatal: proceed with whatever health we had before
        logger.debug("[SkillLibrary] Could not refresh health after combat")

    logger.info("[SkillLibrary] Threat handled — resuming skill")
    return True, None


async def execute_skill(
    skill: Skill,
    bridge: MinecraftBridge,
    context: dict[str, Any] | None = None,
    *,
    threat_check_interval: int = 3,
) -> SkillResult:
    """Execute all steps of *skill* via *bridge*.

    For each step:
      1. Periodically check for threats (see *threat_check_interval*).
      2. Check step-level preconditions.
      3. Send the command through the bridge.
      4. On failure, retry up to ``step.retry`` times.
      5. Merge returned data into *context* for downstream steps.

    Args:
        threat_check_interval: Check ``context["threat_level"]`` every N steps.
            Set to ``0`` to disable threat interruption entirely.

    Updates ``skill.success_count`` / ``skill.fail_count`` / ``skill.avg_duration``
    on completion.
    """
    ctx: dict[str, Any] = dict(context) if context else {}
    start = time.monotonic()

    # Skill-level preconditions
    if not check_preconditions(skill.preconditions, ctx):
        duration = time.monotonic() - start
        await _update_stats(skill, success=False, duration=duration)
        return SkillResult(
            success=False,
            skill_id=skill.id,
            failed_at=-1,
            reason="Skill-level preconditions not met",
            duration=duration,
        )

    # Iterate steps
    for idx, step in enumerate(skill.steps):
        # ── Threat interruption ───────────────────────────────────────────
        if threat_check_interval > 0 and idx % threat_check_interval == 0:
            threat_level = ctx.get("threat_level", 0)
            if threat_level >= 2:
                ok, reason = await _handle_threat(bridge, ctx)
                if not ok:
                    duration = time.monotonic() - start
                    await _update_stats(skill, success=False, duration=duration)
                    return SkillResult(
                        success=False,
                        skill_id=skill.id,
                        failed_at=idx,
                        reason=reason,
                        duration=duration,
                    )

        # Step-level preconditions
        if not check_preconditions(step.preconditions, ctx):
            duration = time.monotonic() - start
            await _update_stats(skill, success=False, duration=duration)
            return SkillResult(
                success=False,
                skill_id=skill.id,
                failed_at=idx,
                reason=f"Step {idx} ({step.name}) preconditions not met",
                duration=duration,
            )

        # Execute with retry
        attempts = 1 + step.retry
        last_error: str | None = None

        for attempt in range(attempts):
            try:
                resp = await bridge.send_command(
                    step.name, step.params, timeout=step.timeout
                )
            except TimeoutError:
                last_error = f"Step {idx} ({step.name}) timed out after {step.timeout}s"
                logger.warning(
                    f"[SkillLibrary] {last_error} (attempt {attempt + 1}/{attempts})"
                )
                continue
            except Exception as exc:
                last_error = f"Step {idx} ({step.name}) raised {type(exc).__name__}: {exc}"
                logger.warning(
                    f"[SkillLibrary] {last_error} (attempt {attempt + 1}/{attempts})"
                )
                continue

            status = resp.get("status", "error")
            if status == "success":
                # Merge result into context for downstream steps
                result_data = resp.get("result")
                if isinstance(result_data, dict):
                    ctx.update(result_data)
                elif result_data is not None:
                    ctx[f"step_{idx}_result"] = result_data
                last_error = None
                break

            last_error = (
                f"Step {idx} ({step.name}) returned error: {resp.get('result', 'unknown')}"
            )
            logger.warning(
                f"[SkillLibrary] {last_error} (attempt {attempt + 1}/{attempts})"
            )

        # All retries exhausted
        if last_error is not None:
            duration = time.monotonic() - start
            await _update_stats(skill, success=False, duration=duration)
            return SkillResult(
                success=False,
                skill_id=skill.id,
                failed_at=idx,
                reason=last_error,
                duration=duration,
            )

    # All steps succeeded
    duration = time.monotonic() - start
    await _update_stats(skill, success=True, duration=duration)
    return SkillResult(
        success=True,
        skill_id=skill.id,
        duration=duration,
        context_updates=ctx,
    )


async def _update_stats(skill: Skill, *, success: bool, duration: float) -> None:
    """Update running statistics on *skill*."""
    if success:
        skill.success_count += 1
    else:
        skill.fail_count += 1

    # Exponential moving average for duration
    total = skill.success_count + skill.fail_count
    if total == 1:
        skill.avg_duration = duration
    else:
        skill.avg_duration = skill.avg_duration * 0.8 + duration * 0.2

    skill.last_used = datetime.now().isoformat()


# ── SQLite Persistence Layer ─────────────────────────────────────────────────

_SKILLS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    parameters_json TEXT DEFAULT '{}',
    preconditions_json TEXT DEFAULT '[]',
    body_json TEXT DEFAULT '{}',
    steps_json TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    postconditions_json TEXT DEFAULT '[]',
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    avg_duration REAL DEFAULT 0.0,
    last_used TEXT DEFAULT '',
    tags_json TEXT DEFAULT '[]',
    is_learned INTEGER DEFAULT 0,
    validated INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


class SkillLibraryDB:
    """Async SQLite persistence for SkillLibrary.

    Write-through cache: all mutations go to both memory and SQLite.
    Reads come from memory (fast); SQLite is only read on startup to hydrate.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open connection and create table if needed."""
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_SKILLS_TABLE_SQL)
        await self._db.commit()
        logger.info(f"[SkillLibraryDB] Connected to {self._db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def load_all(self) -> dict[str, Skill]:
        """Load all skills from SQLite into a dict."""
        if not self._db:
            return {}
        cursor = await self._db.execute("SELECT * FROM skills")
        rows = await cursor.fetchall()
        skills: dict[str, Skill] = {}
        for row in rows:
            skill = self._row_to_skill(row)
            skills[skill.id] = skill
        logger.info(f"[SkillLibraryDB] Loaded {len(skills)} skills from SQLite")
        return skills

    async def save_skill(self, skill: Skill) -> None:
        """Insert or replace a skill in SQLite."""
        if not self._db:
            return
        await self._db.execute(
            """INSERT OR REPLACE INTO skills
            (id, name, description, parameters_json, preconditions_json,
             body_json, steps_json, category, postconditions_json,
             success_count, fail_count, avg_duration, last_used,
             tags_json, is_learned, validated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._skill_to_row(skill),
        )
        await self._db.commit()

    async def update_stats(
        self, skill_id: str, success_count: int, fail_count: int,
        avg_duration: float, last_used: str,
    ) -> None:
        """Update only the stats columns for a skill."""
        if not self._db:
            return
        await self._db.execute(
            """UPDATE skills SET success_count=?, fail_count=?,
            avg_duration=?, last_used=? WHERE id=?""",
            (success_count, fail_count, avg_duration, last_used, skill_id),
        )
        await self._db.commit()

    async def delete_skill(self, skill_id: str) -> None:
        """Delete a skill from SQLite."""
        if not self._db:
            return
        await self._db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        await self._db.commit()

    def _skill_to_row(self, skill: Skill) -> tuple:
        """Convert a Skill to a SQLite row tuple."""
        return (
            skill.id,
            skill.name,
            skill.description,
            json.dumps(skill.parameters, ensure_ascii=False),
            json.dumps(skill.preconditions, ensure_ascii=False),
            json.dumps(skill.body, ensure_ascii=False),
            json.dumps([s.to_dict() for s in skill.steps], ensure_ascii=False),
            skill.category,
            json.dumps(skill.postconditions, ensure_ascii=False),
            skill.success_count,
            skill.fail_count,
            skill.avg_duration,
            skill.last_used,
            json.dumps(skill.tags, ensure_ascii=False),
            int(skill.is_learned),
            int(skill.validated),
        )

    def _row_to_skill(self, row: aiosqlite.Row) -> Skill:
        """Convert a SQLite row to a Skill."""
        return Skill(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            parameters=json.loads(row["parameters_json"] or "{}"),
            preconditions=json.loads(row["preconditions_json"] or "[]"),
            body=json.loads(row["body_json"] or "{}"),
            steps=[SkillStep.from_dict(s) for s in json.loads(row["steps_json"] or "[]")],
            category=row["category"] or "",
            postconditions=json.loads(row["postconditions_json"] or "[]"),
            success_count=row["success_count"],
            fail_count=row["fail_count"],
            avg_duration=row["avg_duration"],
            last_used=row["last_used"] or "",
            tags=json.loads(row["tags_json"] or "[]"),
            is_learned=bool(row["is_learned"]),
            validated=bool(row["validated"]),
        )


class SkillLibrary:
    """Voyager-style skill library with semantic search."""

    COLLECTION_NAME = "mc_skills"

    def __init__(self, atom_store=None, db_path: str | None = None):
        self._store = atom_store
        self._skills: dict[str, Skill] = {}
        self._db: SkillLibraryDB | None = None
        self._db_path = db_path
        logger.info("[SkillLibrary] Initialized")

    async def init_db(self) -> None:
        """Initialize SQLite persistence and load existing skills.

        Call this after construction when db_path was provided.
        """
        if not self._db_path:
            return
        self._db = SkillLibraryDB(self._db_path)
        await self._db.connect()
        self._skills = await self._db.load_all()
        logger.info(f"[SkillLibrary] DB initialized, {len(self._skills)} skills loaded")

    async def close_db(self) -> None:
        """Close the SQLite connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def load_predefined_skills(self) -> int:
        """Load predefined skills into the library.

        Skips skills that already exist (by id). Returns the number of
        skills newly loaded.
        """
        from .predefined_skills import get_predefined_skills

        loaded = 0
        for skill in get_predefined_skills():
            if skill.id not in self._skills:
                await self.save_skill(skill)
                loaded += 1
        if loaded:
            logger.info(f"[SkillLibrary] Loaded {loaded} predefined skills")
        return loaded

    async def save_skill(self, skill: Skill) -> bool:
        """Save skill to library (memory + SQLite)."""
        self._skills[skill.id] = skill
        if self._db:
            await self._db.save_skill(skill)
        logger.info(f"[SkillLibrary] Saved skill: {skill.id}")
        return True

    async def add_learned(self, skill: Skill) -> bool:
        """Add a learned skill with validation and deduplication.

        Marks the skill as ``is_learned=True`` and ``validated=False``.
        Checks for duplicates by id and tag overlap before inserting.
        Returns ``True`` if the skill was added, ``False`` if rejected
        (duplicate or invalid).
        """
        skill.is_learned = True
        skill.validated = False

        # Reject if a skill with the same id already exists
        if skill.id in self._skills:
            existing = self._skills[skill.id]
            if existing.is_learned:
                logger.debug(
                    f"[SkillLibrary] Learned skill '{skill.id}' already exists — skipping"
                )
                return False

        # Reject if tags overlap with an existing learned skill (>50% overlap)
        if skill.tags:
            for existing in self._skills.values():
                if not existing.is_learned or not existing.tags:
                    continue
                overlap = len(set(skill.tags) & set(existing.tags))
                min_len = min(len(skill.tags), len(existing.tags))
                if min_len > 0 and overlap / min_len > 0.5:
                    logger.debug(
                        f"[SkillLibrary] Learned skill '{skill.id}' overlaps with "
                        f"'{existing.id}' (tags: {overlap}/{min_len}) — skipping"
                    )
                    return False

        self._skills[skill.id] = skill
        if self._db:
            await self._db.save_skill(skill)
        logger.info(
            f"[SkillLibrary] Added learned skill: {skill.id} "
            f"(tags={skill.tags}, validated={skill.validated})"
        )
        return True

    async def get_skill(self, skill_id: str) -> Skill | None:
        """Get skill by ID."""
        return self._skills.get(skill_id)

    async def search_skills(self, goal: str, limit: int = 5) -> list[Skill]:
        """Search skills by goal description.

        Returns both predefined and learned skills.  Predefined (non-learned)
        skills are ranked higher than learned skills when scores are equal.
        """
        results: list[tuple[int, bool, Skill]] = []  # (score, is_predefined, skill)
        goal_lower = goal.lower()
        goal_words = set(goal_lower.split())
        for skill in self._skills.values():
            skill_text = f"{skill.name} {skill.description}".lower()
            # Check if any goal word appears in skill text
            score = sum(1 for word in goal_words if word in skill_text)
            if score > 0:
                results.append((score, not skill.is_learned, skill))

        # Sort: higher score first, then predefined before learned
        results.sort(key=lambda r: (-r[0], -r[1]))
        return [skill for _, _, skill in results[:limit]]

    async def search_by_tags(self, tags: list[str], limit: int = 5) -> list[Skill]:
        """Search skills by tags.

        Returns both predefined and learned skills.  Predefined skills
        rank higher when tag match counts are equal.
        """
        results: list[tuple[int, bool, Skill]] = []
        for skill in self._skills.values():
            overlap = sum(1 for tag in tags if tag in skill.tags)
            if overlap > 0:
                results.append((overlap, not skill.is_learned, skill))

        results.sort(key=lambda r: (-r[0], -r[1]))
        return [skill for _, _, skill in results[:limit]]

    async def update_success(self, skill_id: str) -> None:
        """Update skill success count."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.success_count += 1
            skill.last_used = datetime.now().isoformat()
            if self._db:
                await self._db.update_stats(
                    skill_id, skill.success_count, skill.fail_count,
                    skill.avg_duration, skill.last_used,
                )
            logger.info(f"[SkillLibrary] Updated success: {skill_id} ({skill.success_rate:.0%})")

    async def update_failure(self, skill_id: str) -> None:
        """Update skill failure count."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.fail_count += 1
            skill.last_used = datetime.now().isoformat()
            if self._db:
                await self._db.update_stats(
                    skill_id, skill.success_count, skill.fail_count,
                    skill.avg_duration, skill.last_used,
                )
            logger.info(f"[SkillLibrary] Updated failure: {skill_id} ({skill.success_rate:.0%})")

    async def remove_skill(self, skill_id: str) -> None:
        """Remove skill from library (memory + SQLite)."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            if self._db:
                await self._db.delete_skill(skill_id)
            logger.info(f"[SkillLibrary] Removed skill: {skill_id}")

    async def get_all_skills(self) -> list[Skill]:
        """Get all skills."""
        return list(self._skills.values())

    async def get_learned_skills(self) -> list[Skill]:
        """Get all learned (non-predefined) skills."""
        return [s for s in self._skills.values() if s.is_learned]

    async def execute_skill_by_id(
        self,
        skill_id: str,
        bridge: MinecraftBridge,
        context: dict[str, Any] | None = None,
        *,
        threat_check_interval: int = 3,
    ) -> SkillResult:
        """Look up *skill_id* and execute it.

        Returns a ``SkillResult`` with failure if the skill is not found.
        Stats are updated automatically by :func:`execute_skill`.
        """
        skill = self._skills.get(skill_id)
        if skill is None:
            return SkillResult(
                success=False,
                skill_id=skill_id,
                reason=f"Skill '{skill_id}' not found in library",
            )

        return await execute_skill(
            skill, bridge, context,
            threat_check_interval=threat_check_interval,
        )

    # ── Matching & filtering ───────────────────────────────────────────────

    async def match_skills(
        self, context: dict[str, Any], limit: int = 5
    ) -> list[Skill]:
        """Return skills whose preconditions are all satisfied by *context*.

        Results are sorted by success_rate (descending) then avg_duration
        (ascending), and capped at *limit*.
        """
        candidates: list[Skill] = []
        for skill in self._skills.values():
            if check_preconditions(skill.preconditions, context):
                candidates.append(skill)

        # Sort: higher success_rate first, then shorter avg_duration
        candidates.sort(
            key=lambda s: (-s.success_rate, s.avg_duration),
        )
        return candidates[:limit]

    async def search_by_keyword(
        self, keyword: str, limit: int = 5
    ) -> list[Skill]:
        """Search skills by *keyword* in name, description, or tags.

        Case-insensitive substring match.  Skills are scored by how many
        fields match (name=2, description=1, tags=2) and sorted descending.
        Predefined skills rank higher than learned skills at equal scores.
        """
        kw = keyword.lower()
        scored: list[tuple[int, bool, Skill]] = []
        for skill in self._skills.values():
            score = 0
            if kw in skill.name.lower():
                score += 2
            if kw in skill.description.lower():
                score += 1
            if any(kw in tag.lower() for tag in skill.tags):
                score += 2
            if score > 0:
                scored.append((score, not skill.is_learned, skill))

        scored.sort(key=lambda pair: (-pair[0], -pair[1]))
        return [skill for _, _, skill in scored[:limit]]

    async def get_skills_by_category(self, category: str) -> list[Skill]:
        """Return all skills matching *category* (exact, case-insensitive)."""
        cat_lower = category.lower()
        return [
            s for s in self._skills.values()
            if s.category.lower() == cat_lower
        ]

    # ── Maintenance ───────────────────────────────────────────────────────

    async def cleanup(self) -> int:
        """Remove low-quality learned skills.

        Removes learned skills with ``success_rate < 0.3`` **and**
        ``>= 10`` total executions.  Predefined skills are never removed
        by cleanup.  Skills with fewer than 10 executions are kept
        (not enough data to judge quality).

        Returns the number of skills removed.
        """
        to_remove = []
        for skill in self._skills.values():
            if not skill.is_learned:
                continue
            total = skill.success_count + skill.fail_count
            if skill.success_rate < 0.3 and total >= 10:
                to_remove.append(skill.id)
        for skill_id in to_remove:
            await self.remove_skill(skill_id)
        if to_remove:
            logger.info(
                f"[SkillLibrary] Cleanup removed {len(to_remove)} low-quality learned skills"
            )
        return len(to_remove)
