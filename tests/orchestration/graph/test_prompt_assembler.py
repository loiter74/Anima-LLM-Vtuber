"""Tests for prompt assembler: ordering, empty-section filtering, metadata."""

from animetta.orchestration.prompting.assembler import assemble
from animetta.orchestration.prompting.types import (
    CompiledPrompt,
    PromptSection,
    SectionPriority,
    SectionRole,
)


def test_ordering_by_priority():
    """Lower priority number renders first."""
    sections = [
        PromptSection("memory", SectionRole.MEMORY, SectionPriority.MEMORY, "MEM"),
        PromptSection("persona", SectionRole.PERSONA, SectionPriority.PERSONA, "PER"),
    ]
    result = assemble(sections)
    assert result.system_prompt.startswith("PER")
    assert result.system_prompt.endswith("MEM")


def test_stable_order_same_priority():
    """Same priority sorts by name."""
    sections = [
        PromptSection("b_section", SectionRole.MEMORY, 300, "B"),
        PromptSection("a_section", SectionRole.MEMORY, 300, "A"),
    ]
    result = assemble(sections)
    assert result.system_prompt.index("A") < result.system_prompt.index("B")


def test_empty_sections_omitted():
    """Empty and whitespace-only sections are excluded."""
    sections = [
        PromptSection("a", SectionRole.PERSONA, 100, "CONTENT"),
        PromptSection("b", SectionRole.MEMORY, 200, ""),
        PromptSection("c", SectionRole.MEMORY, 300, "   \n  "),
    ]
    result = assemble(sections)
    assert result.section_count == 1
    assert result.section_names == ["a"]
    assert "CONTENT" in result.system_prompt
    assert "---" not in result.system_prompt


def test_warnings_for_omitted_sections():
    """Omitted sections produce warnings."""
    sections = [
        PromptSection("ok", SectionRole.PERSONA, 100, "text"),
        PromptSection("empty", SectionRole.MEMORY, 200, ""),
    ]
    result = assemble(sections)
    assert any("empty" in w for w in result.warnings)


def test_section_warnings_collected():
    """Warnings inside section metadata are included."""
    sections = [
        PromptSection(
            "mem", SectionRole.MEMORY, 200, "context",
            metadata={"warnings": ["recall partial"]},
        ),
    ]
    result = assemble(sections)
    assert any("recall partial" in w for w in result.warnings)


def test_memory_included_flag():
    """memory_included is True when a memory-role section is present."""
    sections = [
        PromptSection("persona", SectionRole.PERSONA, 100, "P"),
        PromptSection("mem", SectionRole.MEMORY, 200, "M"),
    ]
    result = assemble(sections)
    assert result.memory_included is True
    assert result.memory_atom_count == 0  # no atom_count metadata


def test_memory_atom_count():
    """memory_atom_count sums atom_count from memory sections."""
    sections = [
        PromptSection("mem", SectionRole.MEMORY, 200, "M", metadata={"atom_count": 3}),
    ]
    result = assemble(sections)
    assert result.memory_atom_count == 3


def test_empty_input():
    """No sections produces empty prompt."""
    result = assemble([])
    assert result.system_prompt == ""
    assert result.section_count == 0
    assert result.section_names == []
