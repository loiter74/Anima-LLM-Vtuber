"""Prompt pipeline: unified system prompt compilation for LLM calls."""

from .assembler import assemble
from .context import build_context
from .delivery import apply_to_messages
from .pipeline import compile as compile_prompt
from .types import (
    CompiledPrompt,
    PromptContext,
    PromptSection,
    SectionPriority,
    SectionRole,
)

__all__ = [
    "CompiledPrompt",
    "PromptContext",
    "PromptSection",
    "SectionPriority",
    "SectionRole",
    "apply_to_messages",
    "assemble",
    "build_context",
    "compile_prompt",
]
