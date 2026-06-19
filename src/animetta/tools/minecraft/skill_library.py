"""
Skill Library - Voyager-style skill storage, retrieval, and composition

Skills are stored as atoms in Chroma (semantic search) with metadata in SQLite.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger


@dataclass
class Skill:
    """A reusable, composable Minecraft action skill."""
    id: str
    name: str
    description: str
    parameters: dict[str, str] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    body: dict = field(default_factory=dict)  # {type: "plan", steps: [...]} or {type: "macro", func: "..."}
    postconditions: list[str] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    avg_duration: float = 0.0
    last_used: str = ""
    tags: list[str] = field(default_factory=list)
    
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
            "postconditions": self.postconditions,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        return cls(**data)


class SkillLibrary:
    """Voyager-style skill library with semantic search."""
    
    COLLECTION_NAME = "mc_skills"
    
    def __init__(self, atom_store=None):
        self._store = atom_store
        self._skills: dict[str, Skill] = {}
        logger.info("[SkillLibrary] Initialized")
    
    async def save_skill(self, skill: Skill) -> bool:
        """Save skill to library."""
        self._skills[skill.id] = skill
        logger.info(f"[SkillLibrary] Saved skill: {skill.id}")
        return True
    
    async def get_skill(self, skill_id: str) -> Skill | None:
        """Get skill by ID."""
        return self._skills.get(skill_id)
    
    async def search_skills(self, goal: str, limit: int = 5) -> list[Skill]:
        """Search skills by goal description."""
        # Simple keyword matching for now
        results = []
        goal_lower = goal.lower()
        goal_words = set(goal_lower.split())
        for skill in self._skills.values():
            skill_text = f"{skill.name} {skill.description}".lower()
            # Check if any goal word appears in skill text
            if any(word in skill_text for word in goal_words):
                results.append(skill)
        return results[:limit]
    
    async def search_by_tags(self, tags: list[str], limit: int = 5) -> list[Skill]:
        """Search skills by tags."""
        results = []
        for skill in self._skills.values():
            if any(tag in skill.tags for tag in tags):
                results.append(skill)
        return results[:limit]
    
    async def update_success(self, skill_id: str) -> None:
        """Update skill success count."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.success_count += 1
            skill.last_used = datetime.now().isoformat()
            logger.info(f"[SkillLibrary] Updated success: {skill_id} ({skill.success_rate:.0%})")
    
    async def update_failure(self, skill_id: str) -> None:
        """Update skill failure count."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.fail_count += 1
            skill.last_used = datetime.now().isoformat()
            logger.info(f"[SkillLibrary] Updated failure: {skill_id} ({skill.success_rate:.0%})")
    
    async def remove_skill(self, skill_id: str) -> None:
        """Remove skill from library."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            logger.info(f"[SkillLibrary] Removed skill: {skill_id}")
    
    async def get_all_skills(self) -> list[Skill]:
        """Get all skills."""
        return list(self._skills.values())
    
    async def cleanup(self) -> None:
        """Remove low-quality skills."""
        to_remove = []
        for skill in self._skills.values():
            total = skill.success_count + skill.fail_count
            if skill.success_rate < 0.3 and total >= 10:
                to_remove.append(skill.id)
        for skill_id in to_remove:
            await self.remove_skill(skill_id)
