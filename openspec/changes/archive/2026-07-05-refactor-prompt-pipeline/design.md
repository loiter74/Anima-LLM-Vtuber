## Context

Animetta currently constructs the final LLM system prompt through several cooperating but loosely coordinated pieces:

- the orchestrator initializes `state["system_prompt"]` from persona configuration
- `personality_node` derives runtime mode and mood, then stores a textual overlay in metadata
- `MemoryMiddleware.before_llm_call()` recalls memory and can inject memory into prompt text
- `llm_node` appends overlays, enriches prompts, chooses tool or streaming mode, and delivers the final prompt to the provider

This works, but the final prompt has no single owner. New contributors such as livestream behavior, memory recall, tool instructions, safety rules, or future world-state context would add more string concatenation paths unless prompt compilation becomes a dedicated subsystem.

The refactor affects backend orchestration only. It must preserve persona YAML semantics, LLM provider APIs, graph topology, and existing compatibility metadata during migration.

## Goals / Non-Goals

**Goals:**

- Make `PromptPipeline.compile()` the only source of final system prompt text.
- Represent prompt content as ordered `PromptSection` values before rendering.
- Keep runtime personality, memory recall, persona content, and tool instructions as separate sources.
- Ensure tool-calling and streaming modes receive the same compiled system prompt.
- Add debug metadata that identifies included sections, omitted sections, and memory counts without logging full sensitive prompt content by default.
- Preserve old compatibility fields and helper behavior long enough for existing tests and callers to migrate safely.

**Non-Goals:**

- Do not change persona YAML schemas or persona wording.
- Do not change LLM provider interfaces such as `chat_stream()` or `chat_with_tools()`.
- Do not rewrite LangGraph topology or graph builder behavior.
- Do not replace the memory system or alter recall ranking semantics.
- Do not introduce a new tokenizer dependency in the first implementation pass.
- Do not remove `metadata["personality_overlay"]` in this change.

## Decisions

### Decision 1: Add `src/animetta/orchestration/prompting/`

Create a dedicated package for prompt compilation:

- `types.py`: dataclasses and enums for `PromptContext`, `PromptSection`, `CompiledPrompt`, source roles, and priorities.
- `context.py`: extracts prompt-relevant data from `AgentState`, `RunnableConfig`, and service context.
- `sources.py`: prompt sources that convert context into sections.
- `assembler.py`: deterministic ordering, section filtering, rendering, and metadata creation.
- `delivery.py`: mode-specific delivery helpers for tool-calling and streaming.
- `pipeline.py`: public async compile entrypoint.

Alternative considered: keep helpers inside `llm_node.py`. Rejected because `llm_node.py` already handles validation, RAG timing, provider calls, tool fallback, streaming, interrupt handling, and response normalization.

### Decision 2: Compile structured sections, not raw prompt fragments

Each prompt contributor returns zero or more `PromptSection` objects with a stable `name`, `role`, `priority`, `content`, and metadata. The assembler renders these sections into final text in one place.

Alternative considered: pass a list of strings. Rejected because anonymous strings do not support reliable ordering, diagnostics, selective omission, or tests that assert which source contributed content.

### Decision 3: Keep compatibility during migration

`personality_node` will continue writing existing metadata fields, including `personality_overlay`, `personality_mode`, `personality_mood`, character knowledge boundaries, and MBTI values. The new pipeline will prefer structured fields but can fall back to existing metadata while migration is in progress.

Alternative considered: remove old metadata immediately. Rejected because frontend panels, tests, or downstream code may rely on those fields independently of prompt assembly.

### Decision 4: Memory middleware recalls, prompt pipeline renders

Memory middleware should provide structured recall context or a memory section input. It should not own final system prompt injection in the new path. Existing `before_llm_call()` and `_inject_into_prompt()` can remain as compatibility methods, but new prompt compilation must not call them for final assembly.

Alternative considered: let memory middleware keep returning an already enriched prompt. Rejected because that preserves two prompt assembly owners and makes section ordering ambiguous.

### Decision 5: Delivery is separate from assembly

Tool-calling and streaming paths need different transport mechanics, but not different prompt content. Delivery adapters will apply a `CompiledPrompt` to either `chat_with_tools(system_prompt=...)` or streaming message/system prompt setup.

Alternative considered: keep prompt application inline in each LLM path. Rejected because it causes drift between tool and streaming modes.

## Risks / Trade-offs

- Prompt ordering regression -> Mitigation: add assembler and pipeline tests that assert section order and identical compiled prompt delivery across tool and streaming modes.
- Memory context loss during migration -> Mitigation: keep compatibility behavior and test memory-present, memory-empty, and recall-error scenarios.
- Sensitive prompt debug leakage -> Mitigation: debug metadata records section names, counts, and warnings, not full prompt text by default.
- Bigger refactor surface -> Mitigation: implement in phases, with pure dataclass/assembler tests before wiring `llm_node`.
- Existing tests expect old helper behavior -> Mitigation: keep `_enrich_system_prompt()` and old `MemoryMiddleware.before_llm_call()` behavior until new tests pass and callers are migrated.

## Migration Plan

1. Add prompting package with pure types and assembler.
2. Add tests for section rendering, ordering, empty sections, and metadata.
3. Add prompt context builder and sources for persona, runtime personality, memory, and tool instructions.
4. Add pipeline tests using fake state/config/service context.
5. Update memory middleware with a structured recall method while preserving existing compatibility methods.
6. Update personality node to emit structured runtime personality metadata while preserving existing fields.
7. Update `llm_node` to call `PromptPipeline.compile()` and pass `CompiledPrompt.system_prompt` to both tool and streaming paths.
8. Keep old helpers temporarily and mark them as compatibility/deprecated in comments or docstrings.
9. Run targeted orchestration tests and new prompt tests.

Rollback strategy: revert `llm_node` wiring to old prompt assembly while leaving the new prompting package unused. Because provider APIs and graph topology are unchanged, rollback should be localized.

## Open Questions

- The first implementation should use character-length budgeting or no budgeting. Tokenizer-backed budgeting can be added later if prompt size becomes a measured issue.
- The exact debug metadata shape can evolve, but it must include section names and counts in the first implementation.
