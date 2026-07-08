"""Prompt pipeline types: sections, context, and compiled output."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class SectionRole:
    """Semantic role for a prompt section."""
    PERSONA = "persona"
    AFFINITY = "affinity"
    RUNTIME_PERSONALITY = "runtime_personality"
    IMPROVISATION = "improvisation"
    CORRECTION = "correction"
    MEMORY = "memory"
    TOOL_INSTRUCTION = "tool_instruction"


class SectionPriority(IntEnum):
    """Rendering priority (lower number = rendered first)."""
    PERSONA = 100
    AFFINITY = 150  # After persona identity, before runtime personality overlay
    RUNTIME_PERSONALITY = 200
    IMPROVISATION = 225
    CORRECTION = 250  # After runtime personality, before memory
    MEMORY = 300
    TOOL_INSTRUCTION = 400


@dataclass
class PromptSection:
    """A structured prompt section produced by a source."""
    name: str
    role: str
    priority: int
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptContext:
    """All data needed by prompt sources to produce sections."""
    session_id: str
    base_system_prompt: str
    personality_overlay: str
    personality_mode: str
    personality_mood: str | None
    memory_context: str
    memory_metadata: dict[str, Any] = field(default_factory=dict)
    character_known: list[str] = field(default_factory=list)
    character_unknown: list[str] = field(default_factory=list)
    mbti_ei: int = 50
    mbti_sn: int = 50
    mbti_tf: int = 50
    mbti_jp: int = 50
    roleplay_correction: str = ""
    # Affinity — Galgame-style 好感度 toward the current 旅人.
    # Default 50 (neutral); updated each turn from the LLM's [affinity:N] marker.
    affinity: int = 50
    config_version: int = 1
    base_system_prompt_warnings: list[str] = field(default_factory=list)


@dataclass
class CompiledPrompt:
    """Final compiled system prompt with metadata."""
    system_prompt: str
    section_names: list[str] = field(default_factory=list)
    section_count: int = 0
    warnings: list[str] = field(default_factory=list)
    memory_included: bool = False
    memory_atom_count: int = 0
    config_version: int = 1
