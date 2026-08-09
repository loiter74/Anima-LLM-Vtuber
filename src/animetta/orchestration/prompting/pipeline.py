"""Prompt pipeline: compile all sources into a single CompiledPrompt."""

from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig

from .assembler import assemble
from .context import build_context
from .sources import (
    AffinityPromptSource,
    DeveloperLivePromptSource,
    ImprovisedChatPromptSource,
    MemoryPromptSource,
    MinecraftMissionPromptSource,
    PersonaPromptSource,
    RoleplayGuardPromptSource,
    RuntimePersonalityPromptSource,
    SceneGuidancePromptSource,
)
from .types import CompiledPrompt, PromptSection, PromptSource


async def compile(
    state: dict[str, Any],
    config: RunnableConfig | None = None,
    memory_context: str = "",
    memory_metadata: dict[str, Any] | None = None,
) -> CompiledPrompt:
    """Compile all prompt sources into a single CompiledPrompt.

    This is the public entrypoint for prompt compilation.
    It replaces the manual string concatenation in llm_node.

    Args:
        state: LangGraph AgentState dict.
        config: LangGraph RunnableConfig (unused for now, reserved).
        memory_context: Pre-retrieved memory text from MemoryMiddleware.
        memory_metadata: Metadata from memory retrieval.

    Returns:
        CompiledPrompt with final system_prompt and debug metadata.
    """
    ctx = build_context(state, config, memory_context, memory_metadata)

    sources: list[PromptSource] = [
        PersonaPromptSource(),
        AffinityPromptSource(),
        RuntimePersonalityPromptSource(),
        SceneGuidancePromptSource(),
        ImprovisedChatPromptSource(),
        DeveloperLivePromptSource(),
        RoleplayGuardPromptSource(),
        MemoryPromptSource(),
        MinecraftMissionPromptSource(),
    ]

    sections: list[PromptSection] = []
    for src in sources:
        try:
            sections.extend(src.sections(ctx))
        except Exception as exc:
            # Source failure: add warning, continue
            from .types import SectionPriority, SectionRole

            sections.append(
                PromptSection(
                    name=src.name,
                    role=SectionRole.PERSONA,
                    priority=SectionPriority.PERSONA,
                    content="",
                    metadata={"warnings": [f"Source failed: {exc}"]},
                )
            )

    compiled = assemble(sections)
    compiled.warnings.extend(ctx.scene_guidance_warnings)
    compiled.config_version = ctx.config_version
    return compiled
