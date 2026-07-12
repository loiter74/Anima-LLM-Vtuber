# ADRs — ARCHITECTURE DECISION RECORDS

**Generated:** 2026-06-15
**Commit:** 10735c3

> Parent: [../../AGENTS.md](../../AGENTS.md) — root project conventions.

## OVERVIEW

11 Architecture Decision Records documenting binding technical choices. ADRs are **rationale only** — the enforced rules live in `AGENTS.md`. Each ADR follows Michael Nygard's format: Context → Decision → Status → Consequences.

## INDEX

All 11 ADRs are `Accepted` (see `README.md`). Each row states the irreversible decision and what it forbids.

| # | Title | Irreversible decision / forbids |
|---|-------|----------------------------------|
| 001 | [LangGraph over EventBus](ADR-001-langgraph-over-eventbus.md) | LangGraph is the **sole** orchestration mode. ❌ EventBus forbidden (root CRITICAL anti-pattern); no direct function pipelines, Celery, or `transitions` lib. |
| 002 | [Hybrid Search](ADR-002-hybrid-search.md) | Memory retrieval is **always hybrid** (Chroma vector + SQLite FTS5). ❌ No single-strategy retrieval; no Pinecone/Weaviate/Qdrant. |
| 003 | [Plugin Architecture](ADR-003-plugin-architecture.md) | All providers register via `@ProviderRegistry`. ❌ No `if/elif` provider dispatch; no direct instantiation in graph nodes. |
| 004 | [Streaming-First Response](ADR-004-streaming-response.md) | Responses stream token-by-token via LangGraph `astream`. ❌ Never buffer a full LLM response before sending. |
| 005 | [Wiki Memory](ADR-005-wiki-memory.md) | Markdown is source of truth; Chroma/SQLite indexes are derived & rebuildable. ❌ No Mem0/MemGPT; old wiki/storage/learner dirs are DELETED — do not recreate. |
| 006 | [Observability Stack](ADR-006-observability-stack.md) | OTel + Prometheus + Grafana is the only telemetry path. ❌ No competing telemetry frameworks; all spans/metrics flow through `tracing/`. |
| 007 | [Wiki Memory Extensions](ADR-007-wiki-memory-extensions.md) | Atom-based V2 memory model (built on ADR-005). ❌ Extension layer must remain atom-typed; no ad-hoc memory shapes. |
| 008 | [MCP Bridge](ADR-008-mcp-bridge.md) | External tools integrate through the MCP bridge. ❌ No bespoke per-tool IPC protocols alongside it. |
| 009 | [Live2D Expression](ADR-009-live2d-expression.md) | Emotion→param via `IEmotionAnalyzer`→`ITimelineStrategy`→`IEmotionParamMapper`. ❌ Never use real-time `getBounds()` for scaling — cache `baseBounds`. |
| 010 | [Bilibili Meme Collection](ADR-010-bilibili-meme-collection.md) | Meme pipeline bound to Bilibili source + scoring schema. ❌ No parallel ad-hoc meme stores. |
| 011 | [Real-time Audio Pipeline](ADR-011-realtime-audio-pipeline.md) | Audio I/O routes through the unified realtime pipeline. ❌ No per-feature raw audio handling. |

## CONVENTIONS

- **Filename:** `ADR-NNN-kebab-case-title.md` (zero-padded 3-digit number; matches existing `ADR-001..ADR-011`)
- **Nygard format:** `# ADR-NNN: Title` → `**Date:**` → `**Status:**` (Proposed / Accepted / Deprecated / Superseded by ADR-NNN) → `## Context` → `## Decision` → `## Consequences` → `## Alternatives Considered`
- **Status flow:** Proposed → Accepted. Never silently delete an accepted ADR — write a superseding ADR and mark the old one `Superseded by ADR-NNN`.
- **Mermaid diagrams** welcome in `## Decision` (see ADR-001, ADR-005).
- ADRs hold **rationale only** — the enforced NEVER/⚠️ rules live in root `AGENTS.md` anti-patterns and trace back here.

## WHERE TO LOOK

| Question | Read |
|----------|------|
| Find why a rule exists | Browse ADRs — they are the upstream source of truth |
| "Can I add an EventBus / event handler?" | ADR-001 → **No** |
| "Which retrieval strategy for memory?" | ADR-002 (hybrid) + ADR-005 (markdown source of truth) |
| "How do I add a new LLM/TTS provider?" | ADR-003 (`@ProviderRegistry`) |
| "Why is everything async + streaming?" | ADR-004 |
| "Where does memory data live; can I rebuild it?" | ADR-005 + ADR-007 |
| "How do I instrument a new node?" | ADR-006 |
| "How do external tools plug in?" | ADR-008 |
| "Why are Live2D params computed this way?" | ADR-009 (cached `baseBounds`) |
| "How does the meme/singing pipeline source audio?" | ADR-010, ADR-011 |
| Add a new ADR | Next number, Nygard format, update `README.md` index |

## NOTES

- ADRs hold **rationale only** — the enforced NEVER/⚠️ rules live in root `AGENTS.md` anti-patterns and trace back to ADRs here
- ADR-001 (LangGraph) is the most-referenced decision — multiple anti-patterns trace back to it
- ADR-002 locks Chroma as the only vector DB — do not introduce alternatives without superseding this ADR
- ADR-003 establishes `@ProviderRegistry` — every service type (llm/asr/tts/vad/vc/separation) follows this
- ADR-005 replaced the old wiki/storage/learner/meme dirs with atom-based V2 — those dirs are DELETED, do not recreate
