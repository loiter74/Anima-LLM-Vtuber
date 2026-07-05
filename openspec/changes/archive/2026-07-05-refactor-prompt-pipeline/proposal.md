## Why

Prompt construction is currently split across the orchestrator, personality node, memory middleware, and LLM node. This makes final system prompts hard to reason about, difficult to test, and risky to extend with new runtime context such as livestream mode, memory recall, tool instructions, or future world-state inputs.

## What Changes

- Introduce a unified prompt pipeline that compiles all prompt inputs into one `CompiledPrompt`.
- Move final system prompt assembly out of `llm_node.py` and into a dedicated prompting module.
- Convert prompt contributors into structured sources that emit ordered prompt sections instead of directly concatenating strings.
- Keep tool-calling and streaming LLM paths semantically equivalent by delivering the same compiled system prompt to both paths.
- Preserve compatibility fields such as `metadata["personality_overlay"]` during migration, but stop using them as the source of truth for prompt assembly.
- Change memory recall integration so memory retrieval returns structured prompt context and no longer owns final system prompt injection.

## Capabilities

### New Capabilities
- `prompt-pipeline`: Defines the unified prompt compilation contract, prompt section ordering, delivery adapters, and debug metadata for final LLM system prompts.

### Modified Capabilities
- `memory-middleware`: Memory middleware will provide structured recall context for prompt compilation instead of being responsible for injecting memory into a final system prompt.
- `tool-calling`: Tool-calling requests will receive the same compiled prompt contract as streaming requests, with mode-specific delivery isolated from prompt assembly.

## Impact

- Affected backend modules:
  - `src/animetta/orchestration/graph/llm_node.py`
  - `src/animetta/orchestration/graph/memory_middleware.py`
  - `src/animetta/orchestration/graph/personality_node.py`
  - new `src/animetta/orchestration/prompting/` package
- Affected tests:
  - `tests/orchestration/graph/test_llm_node.py`
  - `tests/orchestration/graph/test_memory_middleware.py`
  - `tests/orchestration/graph/test_personality_node.py`
  - new prompt pipeline and assembler tests
- No provider API, persona YAML schema, frontend API, or graph topology changes are intended.
