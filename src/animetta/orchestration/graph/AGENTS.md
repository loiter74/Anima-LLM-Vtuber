# GRAPH — LANGGRAPH STATE GRAPH + NODES

**Generated:** 2026-06-15
**Commit:** 10735c3

> Parent: [../AGENTS.md](../AGENTS.md). This file covers graph internals only.

## OVERVIEW

LangGraph `StateGraph` wiring + node functions + runtime infra. 20 Python files. Nodes are pure state-transformers; all business logic delegates to `services/`.

## STRUCTURE

```
graph/
├── state.py               # AgentState TypedDict + create_initial_state() + log_timing()
├── builder.py             # build_graph() — node wiring, conditional edges, checkpointer
├── orchestrator.py        # LangGraphOrchestrator runtime (12.8 KB)
├── __init__.py            # Re-exports 6 node functions — READ docstring first
│
├── Nodes (async, state→partial-dict) ────────────────────────────
├── asr_node.py            # audio → text
├── personality_node.py    # inject persona/system prompt (imported separately in builder)
├── llm_node.py            # LLM + RAG + streaming — 393 lines, BIGGEST hotspot
├── tool_node.py           # dispatch to ToolManager, returns tool_results
├── tts_node.py            # text → audio
├── emotion_node.py        # text → emotion label + VAD vector
├── output_node.py         # memory write + subtitle — ~309 lines
├── interrupt_handler.py   # user-interrupt checks during streaming
│
├── Helpers (NOT nodes) ──────────────────────────────────────────
├── memory_middleware.py   # MemoryMiddleware CLASS — called inside llm_node, not a node
├── node_error.py          # log_node_error() centralized error helper
├── tool_manager.py        # tool registration + dispatch
├── translation_state.py   # subtitle translation state machine
│
├── Infra (runtime, not on graph) ────────────────────────────────
├── scheduler.py           # background activity scheduler (8.4 KB)
├── observability.py       # Langfuse / OTel hooks
├── stats_handler.py       # StatsCallbackHandler (LangChain callback)
└── stats_store.py         # SQLite persistence — ~360 lines, own _migrate_schema()
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Add a node | `builder.py` `build_graph()` + new `<name>_node.py` + `__init__.py` | Follow `__init__.py` docstring contract |
| Change state shape | `state.py` `AgentState` | TypedDict — update `create_initial_state()` too |
| Understand routing | `builder.py` `route_input`, `should_use_tools` | Conditional entry + tool-loop gate |
| Tool-calling loop | `builder.py:117` `graph.add_edge("tools", "llm")` | llm→tools→llm cycle |
| Fix LLM streaming/RAG | `llm_node.py` | 393 lines — regex emotion tags, memory middleware |
| Redis session sharing | `builder.py` `set_external_checkpointer()` | Overrides MemorySaver when `--redis-url` set |
| Stats schema | `stats_store.py` `_migrate_schema()` | Do not bypass — own migration system |

## GRAPH FLOW (from `builder.py` docstring)

```
[START] --(audio)--> [asr] --┐
        --(text)------------>┴--> [personality] --> [llm] --(tool_calls?)--> [tools] ┐
                                                  │                                 │
                                                  └──(no tools)──> [tts] <──────────┘
                                                                     │
                                                              [emotion] → [output] → [END]
```

- Conditional entry via `set_conditional_entry_point(route_input, ...)`
- `enable_tools=False` (default) → straight `llm → tts` edge, no tools node registered
- Tool loop is a back-edge: `tools → llm` (re-runs LLM with `tool_results` in state)

## CONVENTIONS

- **Node signature**: `async def x_node(state: AgentState) -> dict[str, Any]` — return partial dict, LangGraph merges
- **Config access**: read `RunnableConfig` via the `config: RunnableConfig` parameter, then `config["configurable"]["service_context"]` (NOT `state["_config"]` — that pattern is deprecated)
- **Error handling**: `log_node_error(...)` from `node_error.py`, set `state["error"]`, continue (don't raise)
- **Timing**: call `log_timing(state, step, duration_ms)` — accumulates into `state["_timings"]`
- **Emotion tags**: LLM output may contain `[happy]`/`[sad]` tags — `_strip_emotion_tags()` in `llm_node.py` removes them before TTS

## ANTI-PATTERNS

- ❌ Never put business logic in nodes — delegate to `services/` (parent rule)
- ❌ Never mutate `state` in place — return a partial dict for LangGraph to merge
- ❌ Never construct services inside nodes — pull from `service_context` in `RunnableConfig`
- ❌ Never import `vc_node` — it does not exist here (parent AGENTS.md is stale; VC lives in `services/vc/`)
- ❌ Never re-add `EventBus` — LangGraph is the only orchestration mode (ADR-001)

## NOTES

- `messages` field uses `Annotated[Sequence[BaseMessage], add_messages]` reducer — append semantics, not overwrite
- `AgentState` carries memory-evolution fields (`fuzzy_memories`, `injection_tier`, `meme_candidates`) — populated by `llm_node`, consumed downstream
- `emotion_vad: tuple[float, float, float]` — Valence/Arousal/Dominance vector, used for mood-congruent memory recall
- `personality_node` is NOT in `__init__.py` re-exports — imported directly in `builder.py` (intentional separation)
- Hotspots by size: `llm_node.py` (393) > `stats_store.py` (~360) > `output_node.py` (~309)
- 17 test files in `tests/orchestration/graph/` mirror these modules
