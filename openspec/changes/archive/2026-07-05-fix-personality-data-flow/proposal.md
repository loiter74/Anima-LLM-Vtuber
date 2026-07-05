## Why

`personality_node` writes personality data (overlay, knowledge boundaries, MBTI dimensions) into `state["metadata"]`, but `llm_node` never reads these values. This causes three silent failures:

1. **personality_overlay** (mood/streaming mode instructions) is never injected into the system prompt — LLM never sees "当前情绪：保持积极愉快的语气"
2. **character_known/unknown** never reaches `MemoryMiddleware.before_llm_call()` — knowledge boundary filtering in `CharacterMemoryFilter.filter_by_boundaries()` is dead code
3. **mbti_ei/sn/tf/jp** always defaults to 50/50/50/50 — MBTI-based memory ranking in `CharacterMemoryFilter.rank_by_persona()` is dead code

The personality system's memory integration is completely non-functional.

## What Changes

- `llm_node._retrieve_memory_context()` reads `character_known`, `character_unknown`, `mbti_*` from `state["metadata"]` and passes them to `MemoryMiddleware.before_llm_call()`
- `llm_node` main functions read `personality_overlay` from `state["metadata"]` and append it to `system_prompt` before passing to LLM
- New tests verify the data flows end-to-end (personality_node → state → llm_node → middleware)

## Capabilities

### New Capabilities
- `personality-data-bridge`: Bridge personality_node metadata (overlay, knowledge boundaries, MBTI dimensions) into llm_node's system prompt and memory middleware calls

### Modified Capabilities

## Impact

- **Files**: `src/animetta/orchestration/graph/llm_node.py` (main fix), `tests/test_llm_node_personality_bridge.py` (new)
- **No breaking changes**: All additions use existing function signatures with default fallbacks
- **No API changes**: Internal data flow only, no external interfaces affected
- **Dependencies**: None new; existing `MemoryMiddleware.before_llm_call()` already accepts these parameters
