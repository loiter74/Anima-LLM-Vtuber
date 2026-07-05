"""Prompt sources: convert PromptContext into PromptSection values."""

from __future__ import annotations

from .types import (
    PromptContext,
    PromptSection,
    SectionPriority,
    SectionRole,
)


class PersonaPromptSource:
    """Produces the base persona system prompt section."""

    name = "persona"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        content = ctx.base_system_prompt
        warnings = []
        if not content:
            warnings.append("No base persona prompt available")
        return [PromptSection(
            name=self.name,
            role=SectionRole.PERSONA,
            priority=SectionPriority.PERSONA,
            content=content,
            metadata={"warnings": warnings} if warnings else {},
        )]


class RuntimePersonalityPromptSource:
    """Produces runtime personality overlay section.

    Prefers structured mode/mood from metadata.
    Falls back to personality_overlay string for migration compatibility.
    """

    name = "runtime_personality"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        parts: list[str] = []

        if ctx.personality_mode == "streaming":
            parts.append("当前为直播模式。回复要简短有趣，适合弹幕互动。")

        if ctx.personality_mood:
            mood_map = {
                "happy": "保持积极愉快的语气",
                "sad": "语气温和一些",
                "angry": "保持冷静理性的态度",
                "surprised": "可以适当表达惊讶",
                "thinking": "用思考和分析的语气",
                "neutral": "保持自然平稳的语气",
            }
            desc = mood_map.get(ctx.personality_mood, "")
            if desc:
                parts.append(f"当前情绪：{desc}")

        # Fallback to raw overlay if structured produced nothing
        if not parts and ctx.personality_overlay:
            parts.append(ctx.personality_overlay)

        content = " ".join(parts)
        return [PromptSection(
            name=self.name,
            role=SectionRole.RUNTIME_PERSONALITY,
            priority=SectionPriority.RUNTIME_PERSONALITY,
            content=content,
        )]


class MemoryPromptSource:
    """Produces memory context section from pre-retrieved memory."""

    name = "memory"

    def sections(self, ctx: PromptContext) -> list[PromptSection]:
        if not ctx.memory_context:
            return [PromptSection(
                name=self.name,
                role=SectionRole.MEMORY,
                priority=SectionPriority.MEMORY,
                content="",
            )]

        atom_count = ctx.memory_metadata.get("atom_count", 0)
        return [PromptSection(
            name=self.name,
            role=SectionRole.MEMORY,
            priority=SectionPriority.MEMORY,
            content=ctx.memory_context,
            metadata={"atom_count": atom_count},
        )]
