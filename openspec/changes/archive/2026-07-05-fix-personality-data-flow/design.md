## Context

The LangGraph pipeline has two adjacent nodes: `personality_node` → `llm_node`. The personality node extracts persona configuration (overlay, knowledge boundaries, MBTI dimensions) and writes them to `state["metadata"]`. However, `llm_node` never reads these metadata fields — it only uses `state["system_prompt"]` (set once at orchestrator startup) and passes default values to `MemoryMiddleware`.

This means:
- Mood/streaming overlay instructions never reach the LLM
- `CharacterMemoryFilter.filter_by_boundaries()` receives `character_known=None, character_unknown=None`
- `CharacterMemoryFilter.rank_by_persona()` receives `mbti_*=50` (neutral, no effect)

## Goals / Non-Goals

**Goals:**
- Personality overlay text reaches the LLM as part of system prompt
- Knowledge boundaries and MBTI dimensions flow from personality_node through to memory middleware
- All changes are testable with unit tests

**Non-Goals:**
- Redesigning the personality_node or its output structure
- Changing `MemoryMiddleware.before_llm_call()` or `LivingMemorySystem.recall()` signatures
- Modifying `CharacterMemoryFilter` logic (already correct, just not receiving data)
- Adding new state fields or changing `AgentState` TypedDict

## Decisions

### Decision 1: Bridge at llm_node (not at personality_node)

**Choice**: Read metadata values in `llm_node` and pass them through existing function signatures.

**Alternatives considered**:
- Have personality_node write directly to `state["system_prompt"]` — rejected because it changes personality_node's responsibility and the system_prompt is set once at orchestrator level
- Create a new shared state field — rejected as unnecessary; metadata already carries the data

**Rationale**: Minimal change surface. personality_node's contract stays clean ("produce metadata"), llm_node's contract stays clean ("consume state and call middleware"). The bridge is one read + one pass-through per field.

### Decision 2: Overlay injection point

**Choice**: Read `personality_overlay` in llm_node's main function body, append to system_prompt before `_enrich_system_prompt()`.

**Alternatives considered**:
- Inject in personality_node into `state["system_prompt"]` directly — rejected: personality_node doesn't own system_prompt, orchestrator sets it
- Inject in `_enrich_system_prompt()` — rejected: that function handles memory injection, mixing concerns

**Rationale**: The overlay is a per-request runtime concern (mood changes each turn). Injecting in llm_node keeps the logic colocated with other per-request enrichments.

### Decision 3: Default fallback strategy

**Choice**: Use `state.get("metadata", {}).get("key", default)` pattern — if metadata missing or field missing, fall back to current behavior (None/50/empty).

**Rationale**: Zero regression risk. If personality_node is removed or reconfigured, llm_node degrades gracefully to current behavior.

## Risks / Trade-offs

- **[Risk] Overlay could make system prompt too long** → Mitigation: personality_overlay is already short (1-2 sentences). No change in size.
- **[Risk] metadata key names could drift** → Mitigation: personality_node and llm_node are in the same package, same code review. Low risk.
- **[Trade-off] Coupling via string keys** → Acceptable: this is the existing pattern in the codebase (metadata is dict-based throughout).
