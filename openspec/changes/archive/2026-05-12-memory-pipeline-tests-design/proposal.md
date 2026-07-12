# Memory Pipeline Integration Tests Design

**Date:** 2026-05-12
**Status:** approved

## Scope

Integration tests for the 4 new memory capabilities, exercising the full pipeline with mocked LLM and real storage:

1. `auto-fact-extraction` — LLM fact extraction → MemoryEntryStore → search
2. `emotion-weighted-retrieval` — emotion-tagged storage → weighted retrieval ranking
3. `memory-decay` — decay computation → archive → search exclusion
4. `persona-evolution` — persona analysis → suggestions YAML output

## Architecture

```
tests/memory/test_memory_pipeline.py

Fixtures:
  mock_llm     → returns controlled JSON for fact/pattern/persona prompts
  pipeline     → MemoryEntryStore (:memory:) + FactExtractor + MemoryScorer

5 Scenarios:
  1. extract → store → search        (auto-fact + decay)
  2. emotion → decay → archive       (memory-decay)
  3. emotion-weighted search         (emotion-weighted)
  4. facts → wiki Markdown           (auto-fact)
  5. persona analysis pipeline       (persona-evolution)
```

## Implementation

Single file `tests/memory/test_memory_pipeline.py`, ~150 lines. Mock LLM fixture returns deterministic JSON. In-memory SQLite for isolation. No external dependencies needed beyond pytest.
