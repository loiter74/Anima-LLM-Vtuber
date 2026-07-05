## 1. Prompting Package Skeleton

- [x] 1.1 Create `src/animetta/orchestration/prompting/__init__.py` with public exports for the new prompt pipeline types and entrypoint.
- [x] 1.2 Create `types.py` with `PromptSection`, `PromptContext`, `CompiledPrompt`, and enum or literal types for section roles and priorities.
- [x] 1.3 Create `assembler.py` with deterministic section sorting, empty-section filtering, final prompt rendering, and metadata/warning collection.
- [x] 1.4 Add `tests/orchestration/graph/test_prompt_assembler.py` covering ordering, empty-section omission, metadata, and warning behavior.

## 2. Prompt Context and Sources

- [x] 2.1 Create `context.py` to build `PromptContext` from `AgentState`, `RunnableConfig`, and `service_context` without changing existing graph state semantics.
- [x] 2.2 Create `sources.py` with `PersonaPromptSource`, `RuntimePersonalityPromptSource`, `MemoryPromptSource`, and `ToolInstructionPromptSource`.
- [x] 2.3 Ensure `PersonaPromptSource` uses existing `state["system_prompt"]` or service config fallback without changing persona YAML behavior.
- [x] 2.4 Ensure `RuntimePersonalityPromptSource` consumes structured mode/mood metadata and only falls back to `personality_overlay` for migration compatibility.
- [x] 2.5 Ensure `MemoryPromptSource` renders memory context as a prompt section and does not call memory prompt injection helpers.

## 3. Prompt Pipeline and Delivery

- [x] 3.1 Create `pipeline.py` with async `PromptPipeline.compile(state, config, service_context)` returning `CompiledPrompt`.
- [x] 3.2 Create `delivery.py` with helpers or adapters for applying `CompiledPrompt.system_prompt` to tool-calling and streaming paths.
- [x] 3.3 Add `tests/orchestration/graph/test_prompt_pipeline.py` covering persona-only, persona plus runtime personality, memory present, memory absent, and memory failure scenarios.
- [x] 3.4 Add a test proving tool-calling and streaming delivery use equivalent compiled system prompt text for equivalent state/config.

## 4. Memory Middleware Migration

- [x] 4.1 Add a structured memory recall method to `MemoryMiddleware` that returns memory context and metadata without injecting into a final system prompt.
- [x] 4.2 Preserve `before_llm_call()` and `_inject_into_prompt()` compatibility behavior for existing callers and tests.
- [x] 4.3 Update or add memory middleware tests proving the structured path does not assemble the final system prompt.
- [x] 4.4 Ensure memory retrieval errors are caught and converted into safe empty memory context plus warning metadata.

## 5. Personality Metadata Migration

- [x] 5.1 Update `personality_node.py` to emit `metadata["runtime_personality"]` with structured `mode` and `mood` values.
- [x] 5.2 Preserve existing `personality_overlay`, `personality_mode`, `personality_mood`, character knowledge, and MBTI metadata fields.
- [x] 5.3 Update `tests/orchestration/graph/test_personality_node.py` to assert both compatibility metadata and structured runtime personality metadata.

## 6. LLM Node Integration

- [x] 6.1 Update `llm_node.py` so prompt compilation happens through `PromptPipeline.compile()` before provider calls.
- [x] 6.2 Remove manual prompt concatenation from `_llm_with_tools()` and `_llm_without_tools()`.
- [x] 6.3 Pass `CompiledPrompt.system_prompt` to `chat_with_tools()` in tool-calling mode.
- [x] 6.4 Pass `CompiledPrompt.system_prompt` to `chat_stream()` and any inserted `SystemMessage` in streaming mode.
- [x] 6.5 Preserve existing tool fallback, timeout handling, interrupt handling, response chunking, and `_notify_middleware_after()` behavior.
- [x] 6.6 Keep `_enrich_system_prompt()` only as a deprecated compatibility helper if existing tests or callers still require it.

## 7. Verification

- [x] 7.1 Run `PYTHONPATH=src python -m pytest tests/orchestration/graph/test_prompt_assembler.py -v`.
- [x] 7.2 Run `PYTHONPATH=src python -m pytest tests/orchestration/graph/test_prompt_pipeline.py -v`.
- [x] 7.3 Run `PYTHONPATH=src python -m pytest tests/orchestration/graph/test_memory_middleware.py -v`.
- [x] 7.4 Run `PYTHONPATH=src python -m pytest tests/orchestration/graph/test_personality_node.py -v`.
- [x] 7.5 Run `PYTHONPATH=src python -m pytest tests/orchestration/graph/test_llm_node.py -v`.
- [x] 7.6 Run `ruff check src/animetta/orchestration/graph src/animetta/orchestration/prompting tests/orchestration/graph`.

## 8. Cleanup and Documentation

- [x] 8.1 Confirm no new prompt string concatenation remains in `llm_node.py` for persona, runtime personality, or memory sections.
- [x] 8.2 Confirm prompt debug metadata includes section names, section count, warnings, and memory inclusion metadata without logging full prompt text by default.
- [x] 8.3 Update comments or docstrings to mark old prompt injection helpers as compatibility-only.
- [x] 8.4 Review the change against `openspec/changes/refactor-prompt-pipeline/specs/**/*.md` and confirm each requirement has test coverage or an explicit verification step.
