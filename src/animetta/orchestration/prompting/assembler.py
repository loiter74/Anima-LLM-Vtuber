"""Prompt assembler: sorts sections, filters empties, renders final prompt."""

from __future__ import annotations

from .types import CompiledPrompt, PromptSection

_SECTION_SEP = "\n\n---\n\n"


def assemble(sections: list[PromptSection]) -> CompiledPrompt:
    """Assemble prompt sections into a final CompiledPrompt.

    Rules:
    - Sort by priority (ascending), then by name for stable ordering.
    - Skip sections with empty/whitespace-only content.
    - Join remaining sections with ``\\n\\n---\\n\\n``.
    - Collect section names, count, and warnings into metadata.
    """
    # Filter empty
    active = [s for s in sections if s.content and s.content.strip()]
    skipped = [s.name for s in sections if not s.content or not s.content.strip()]

    # Sort
    active.sort(key=lambda s: (s.priority, s.name))

    # Render
    system_prompt = _SECTION_SEP.join(s.content for s in active)

    # Warnings for skipped sections
    warnings = [f"Section '{name}' omitted (empty content)" for name in skipped]

    # Collect warnings from individual sections
    for s in active:
        for w in s.metadata.get("warnings", []):
            warnings.append(f"[{s.name}] {w}")

    return CompiledPrompt(
        system_prompt=system_prompt,
        section_names=[s.name for s in active],
        section_count=len(active),
        warnings=warnings,
        memory_included=any(s.role == "memory" for s in active),
        memory_atom_count=sum(
            s.metadata.get("atom_count", 0) for s in active if s.role == "memory"
        ),
    )
