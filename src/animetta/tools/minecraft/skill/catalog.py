"""Skill catalog, search, and persistence facade."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from .conditions import check_preconditions
from .models import Skill, SkillTrustStage
from .store import SkillLibraryDB


class SkillLibrary:
    """Voyager-style skill library with in-memory search and optional SQLite."""

    COLLECTION_NAME = "mc_skills"

    def __init__(self, atom_store: object | None = None, db_path: str | None = None) -> None:
        self._store = atom_store
        self._skills: dict[str, Skill] = {}
        self._db: SkillLibraryDB | None = None
        self._db_path = db_path
        logger.info("[SkillLibrary] Initialized")

    async def init_db(self) -> None:
        """Initialize SQLite persistence and load existing skills."""
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
        """Load predefined skills into the library."""
        from .predefined import get_predefined_skills

        loaded = 0
        for skill in get_predefined_skills():
            if skill.id not in self._skills:
                await self.save_skill(skill)
                loaded += 1
        if loaded:
            logger.info(f"[SkillLibrary] Loaded {loaded} predefined skills")
        return loaded

    async def save_skill(self, skill: Skill) -> bool:
        """Save skill to library."""
        self._skills[skill.id] = skill
        if self._db:
            await self._db.save_skill(skill)
        logger.info(f"[SkillLibrary] Saved skill: {skill.id}")
        return True

    async def add_learned(self, skill: Skill) -> bool:
        """Add a learned skill with validation and deduplication."""
        skill.is_learned = True
        skill.validated = False
        skill.trust_stage = SkillTrustStage.CANDIDATE

        if skill.id in self._skills:
            existing = self._skills[skill.id]
            if existing.is_learned:
                logger.debug(f"[SkillLibrary] Learned skill '{skill.id}' already exists — skipping")
                return False

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

    async def demote_skill(self, skill_id: str, *, reason: str, session_id: str) -> bool:
        """Move a trusted skill back to candidate while preserving audit history."""
        skill = self._skills.get(skill_id)
        if skill is None:
            return False
        skill.trust_stage = SkillTrustStage.CANDIDATE
        skill.validated = False
        skill.provenance.history.append(
            {
                "event": "demoted",
                "reason": reason,
                "session_id": session_id,
            }
        )
        await self.save_skill(skill)
        return True

    async def promote_skill(
        self,
        skill_id: str,
        *,
        validation_session_id: str,
        evidence_refs: list[str],
        environment_fingerprint: str,
    ) -> bool:
        """Promote a candidate after a separate evidence-backed validation task."""
        skill = self._skills.get(skill_id)
        if skill is None or not validation_session_id or not evidence_refs:
            return False
        skill.trust_stage = SkillTrustStage.TRUSTED
        skill.validated = True
        skill.provenance.validation_session_id = validation_session_id
        skill.provenance.evidence_refs.extend(
            ref for ref in evidence_refs if ref not in skill.provenance.evidence_refs
        )
        skill.provenance.environment_fingerprint = environment_fingerprint
        skill.provenance.history.append(
            {
                "event": "promoted",
                "reason": "independent validation passed",
                "session_id": validation_session_id,
            }
        )
        await self.save_skill(skill)
        return True

    async def get_skill(self, skill_id: str) -> Skill | None:
        """Get skill by ID."""
        return self._skills.get(skill_id)

    async def search_skills(self, goal: str, limit: int = 5) -> list[Skill]:
        """Search skills by goal description."""
        results: list[tuple[int, bool, Skill]] = []
        goal_lower = goal.lower()
        goal_words = set(goal_lower.split())
        for skill in self._skills.values():
            skill_text = f"{skill.name} {skill.description}".lower()
            score = sum(1 for word in goal_words if word in skill_text)
            if score > 0:
                results.append((score, not skill.is_learned, skill))

        results.sort(key=lambda r: (-r[0], -r[1]))
        return [skill for _, _, skill in results[:limit]]

    async def search_by_tags(self, tags: list[str], limit: int = 5) -> list[Skill]:
        """Search skills by tags."""
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
            skill.consecutive_failures = 0
            skill.last_used = datetime.now().isoformat()
            if self._db:
                await self._db.update_stats(
                    skill_id,
                    skill.success_count,
                    skill.fail_count,
                    skill.consecutive_failures,
                    skill.avg_duration,
                    skill.last_used,
                )
            logger.info(f"[SkillLibrary] Updated success: {skill_id} ({skill.success_rate:.0%})")

    async def update_failure(self, skill_id: str) -> None:
        """Update skill failure count."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.fail_count += 1
            skill.consecutive_failures += 1
            skill.last_used = datetime.now().isoformat()
            if self._db:
                await self._db.update_stats(
                    skill_id,
                    skill.success_count,
                    skill.fail_count,
                    skill.consecutive_failures,
                    skill.avg_duration,
                    skill.last_used,
                )
            logger.info(f"[SkillLibrary] Updated failure: {skill_id} ({skill.success_rate:.0%})")

    async def remove_skill(self, skill_id: str) -> None:
        """Remove skill from library."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            if self._db:
                await self._db.delete_skill(skill_id)
            logger.info(f"[SkillLibrary] Removed skill: {skill_id}")

    async def get_all_skills(self) -> list[Skill]:
        """Get all skills."""
        return list(self._skills.values())

    async def get_learned_skills(self) -> list[Skill]:
        """Get all learned skills."""
        return [s for s in self._skills.values() if s.is_learned]

    async def match_skills(self, context: dict[str, Any], limit: int = 5) -> list[Skill]:
        """Return skills whose preconditions are all satisfied."""
        candidates: list[Skill] = []
        for skill in self._skills.values():
            if check_preconditions(skill.preconditions, context):
                candidates.append(skill)

        candidates.sort(key=lambda s: (-s.success_rate, s.avg_duration))
        return candidates[:limit]

    async def match_trusted_skills(self, context: dict[str, Any], limit: int = 5) -> list[Skill]:
        """Return only independently validated skills eligible for live execution."""
        candidates = [
            skill
            for skill in self._skills.values()
            if skill.is_trusted and check_preconditions(skill.preconditions, context)
        ]
        candidates.sort(key=lambda skill: (-skill.success_rate, skill.avg_duration))
        return candidates[:limit]

    async def search_by_keyword(self, keyword: str, limit: int = 5) -> list[Skill]:
        """Search skills by keyword in name, description, or tags."""
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
        """Return all skills matching category."""
        cat_lower = category.lower()
        return [s for s in self._skills.values() if s.category.lower() == cat_lower]

    async def cleanup(self) -> int:
        """Remove low-quality learned skills."""
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
