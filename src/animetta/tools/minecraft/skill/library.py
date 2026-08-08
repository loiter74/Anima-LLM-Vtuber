"""Compatibility facade for Minecraft skill library APIs."""

from __future__ import annotations

from .catalog import SkillLibrary
from .conditions import _COND_PATTERN, _check_single, check_preconditions
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
    "_SKILLS_TABLE_SQL",
    "SkillLibraryDB",
    "SkillLibrary",
]
