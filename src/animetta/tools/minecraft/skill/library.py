"""Compatibility facade for Minecraft skill library APIs."""

from __future__ import annotations

from .catalog import SkillLibrary
from .conditions import _COND_PATTERN, _check_single, check_preconditions
from .executor import _elapsed_since, _handle_threat, _update_stats, execute_skill
from .models import _STEP_PARAM_DEFS, STEP_TYPES, Skill, SkillResult, SkillStep
from .store import _SKILLS_TABLE_SQL, SkillLibraryDB

__all__ = [
    "STEP_TYPES",
    "_STEP_PARAM_DEFS",
    "SkillStep",
    "Skill",
    "SkillResult",
    "_COND_PATTERN",
    "check_preconditions",
    "_check_single",
    "_elapsed_since",
    "_handle_threat",
    "execute_skill",
    "_update_stats",
    "_SKILLS_TABLE_SQL",
    "SkillLibraryDB",
    "SkillLibrary",
]
