# Interview Showcase: Observability + Demo Enhancements

**Date:** 2026-05-01
**Author:** Sisyphus (AI Orchestrator)
**Status:** Design Approved
**Target Role:** AI Application / LLM Engineer

---

## Strategic Approach

**Chosen: Observability-first demo enhancement (A).** Build a live metrics dashboard
in the existing Vue3 frontend, enhance architectural documentation with ADRs and
detailed diagrams, create reproducible performance benchmarks, and produce a
structured interview demo script. Every deliverable is designed to let an interviewer
quickly understand the depth and quality of the system.

```
Dashboard (Vue3)  →  "See it work live"
Architecture docs  →  "Understand the design"
Benchmarks         →  "Know the numbers"
Demo script        →  "Tell the story"
```

---

## Section 1: Vue3 Dashboard

### Data Flow

```
StatsStore (SQLite)  ←  StatsCallbackHandler records traces
       │
       ▼
stats_api.py (FastAPI routes)
  ┌── GET /api/stats/overview
  ├── GET /api/stats/nodes
  ├── GET /api/stats/traces
  └── GET /api/stats/traces/{trace_id}
       │
       ▼ (HTTP JSON)
Vue3 Dashboard Page (/dashboard)
  ├── StatsKpiCards        — Total sessions, tokens, avg latency, error rate
  ├── LatencyBreakdown     — Horizontal bar chart per pipeline node
  ├── TokenUsageChart      — Line chart over time
  ├── ErrorRateCard        — Error rate by node
  ├── SessionTimeline      — Searchable session list with drill-down
  └── ProviderComparison   — Side-by-side LLM provider comparison
```

### Components

| Component | API Source | Display Type |
|-----------|-----------|--------------|
| `StatsKpiCards.vue` | `GET /overview` | Metric cards (4 KPIs) |
| `LatencyBreakdown.vue` | `GET /nodes` | Horizontal bar chart (Chart.js) |
| `TokenUsageChart.vue` | `GET /traces` | Line chart (Chart.js) |
| `ErrorRateCard.vue` | `GET /nodes` | Ring/gauge chart (Chart.js) |
| `SessionTimeline.vue` | `GET /traces` | Searchable table + detail panel |
| `ProviderComparison.vue` | `GET /traces` | Comparison table |

### Tech Stack

- **Chart library**: vue-chartjs (Chart.js wrapper for Vue 3)
- **Styling**: UnoCSS (existing project convention)
- **State**: Pinia store for dashboard data
- **HTTP**: Existing socket/API layer

### Files to Create

```
frontend/src/
├── views/DashboardPage.vue       # Page layout + grid
├── components/dashboard/
│   ├── StatsKpiCards.vue
│   ├── LatencyBreakdown.vue
│   ├── TokenUsageChart.vue
│   ├── ErrorRateCard.vue
│   ├── SessionTimeline.vue
│   └── ProviderComparison.vue
└── stores/dashboardStore.ts      # Pinia store
```

### Non-Goals
- No real-time WebSocket updates (page uses auto-refresh polling)
- No persistent dashboard settings
- No authentication for dashboard (local-only)

---

## Section 2: Architecture Decision Records (ADRs)

### ADR Format

Each ADR follows the template:
```markdown
# ADR-NNN: Title

**Date:** 2026-05-01
**Status:** Accepted

## Context
Why this decision was needed, what constraints existed.

## Decision
What was chosen and how it works.

## Consequences
What becomes easier, harder, or trade-offs introduced.

## Alternatives Considered
Other options that were evaluated and why they were rejected.
```

### ADR List

| ID | Title | Key Alternative |
|----|-------|-----------------|
| ADR-001 | LangGraph over EventBus | EventBus, Direct orchestration, Message queue |
| ADR-002 | Chroma + SQLite FTS5 hybrid search | Pinecone, Weaviate, Pure vector search |
| ADR-003 | Plugin-based provider architecture | Factory pattern, DI container, Service locator |
| ADR-004 | Streaming-first response design | Buffered response, Polling, WebSocket raw |
| ADR-005 | Wiki-architecture memory system | Conversational buffer, Summary memory |

### Files to Create

```
docs/adrs/
├── README.md                  # Index of all ADRs
├── ADR-001-langgraph-over-eventbus.md
├── ADR-002-hybrid-search.md
├── ADR-003-plugin-architecture.md
├── ADR-004-streaming-response.md
└── ADR-005-wiki-memory.md
```

---

## Section 3: Enhanced ARCHITECTURE.md Diagrams

### New Diagrams

Add to existing `ARCHITECTURE.md`:

1. **System Context (C4 Level 1)**
   ```
   [User] --(text/audio)--> [Anima System] --(API calls)--> [LLM Providers]
                                                           --> [TTS Providers]
                                                           --> [ASR Providers]
   ```

2. **Container Diagram (C4 Level 2)**
   ```
   [Vue3 Frontend] --(Socket.IO)--> [FastAPI Backend] --(HTTP)--> [StatsStore SQLite]
                                   [LangGraph Engine] --(HTTP)--> [Chroma Vector DB]
                                   [Session Manager]  --(SQL)--> [SQLite FTS5]
   ```

3. **Sequence Diagram: Full Request Lifecycle**
   ```
   User -> Frontend: Audio input
   Frontend -> Backend: raw_audio_data event
   Backend -> ASR: transcribe(audio)
   ASR -> Backend: text
   Backend -> Memory: retrieve_context(text)
   Memory -> Backend: relevant context
   Backend -> LLM: generate(user_text + context)
   LLM -> Backend: stream tokens
   Backend -> TTS: synthesize(response)
   TTS -> Backend: audio data
   Backend -> Emotion: analyze(response)
   Emotion -> Backend: emotion label
   Backend -> Memory: store_turn(...)
   Backend -> Frontend: text + audio + expression
   Frontend -> Live2D: apply(expression)
   ```

4. **LangGraph State Machine Diagram**
   ```
   [START] --> route_input
     ├── audio --> [asr_node] --> user_text
     └── text --------> [llm_node]
                           ├── tool_calls --> [tool_node] --results--> [llm_node]
                           └── response ----> [tts_node]
                                                |
                                          [emotion_node]
                                                |
                                          [output_node] --> [END]
   ```

5. **Class Hierarchy Diagram**: Service interfaces, Config models, Provider registry

---

## Section 4: Benchmark Script

### Script Design

```bash
python scripts/benchmark.py

Commands:
  quick       Run basic end-to-end latency test (mock providers)
  full        Run comprehensive benchmark (all nodes, repeated)
  compare     Compare multiple LLM providers side-by-side
  report      Generate markdown report from latest run
```

### Metrics

| Metric | Definition |
|--------|-----------|
| E2E Latency | Text input → response_text available |
| Full Pipeline | Audio → ASR → LLM → TTS → output event |
| TTFB | Time to first token of LLM response |
| Tokens/sec | Output tokens / LLM generation time |
| RAG Latency | Memory retrieval time (search + format) |
| Per-node Latency | Individual node execution time |

### Output

Results stored in `docs/benchmarks/results.md`:

```markdown
## Benchmark: 2026-05-01

| Scenario | Provider | P50 | P95 | P99 | Tokens/s |
|----------|----------|-----|-----|-----|----------|
| Text E2E | DeepSeek | 1.2s | 2.1s | 3.0s | 45.2 |
| Text E2E | GLM-4    | 0.8s | 1.5s | 2.2s | 52.1 |
| Text E2E | Mock     | 5ms  | 8ms  | 12ms | —    |
```

---

## Section 5: Interview Demo Script

### Demo Walkthrough (15-20 minutes)

| Step | Time | What You Do | Engineering Story |
|------|------|-------------|-------------------|
| 1 | 2 min | **Basic chat**: Say "你好！今天天气怎么样？" | Show streaming, LangGraph pipeline, emotion-triggered Live2D response |
| 2 | 2 min | **Open Dashboard**: Navigate to `/dashboard` | Show live metrics, per-node latency breakdown, token usage chart |
| 3 | 2 min | **Memory recall**: "还记得我们上次聊了什么吗？" | Demonstrate RAG, hybrid search retrieving past session context |
| 4 | 2 min | **Tool calling**: "搜索一下最近的AI新闻" | Show web_search tool executing via MCP bridge |
| 5 | 2 min | **Provider switch**: Change `config.yaml` to use GLM-4 | Show plugin architecture, provider registry, zero-code config change |
| 6 | 2 min | **Code quality tour**: Open GitHub → show CI badge, 81+ tests, coverage | Testing infrastructure, GitHub Actions, type checking |
| 7 | 3 min | **Architecture tour**: Walk through ARCHITECTURE.md diagrams | LangGraph state machine, hybrid search, ADR decisions |
| 8 | 1 min | **Deployment**: "Runs on Fly.io with one command" | Docker, docker-compose, fly.toml |

### Interview Q&A Preparation

See `docs/demo/interview-qa.md` for anticipated questions and structured answers.

---

## Implementation Phasing

| Phase | Items | Dependency |
|-------|-------|-----------|
| **Phase 1** | Vue3 Dashboard (6 components + store + route) | Existing stats_api.py |
| **Phase 2** | ADRs (5 documents) | None |
| **Phase 3** | Enhanced ARCHITECTURE.md | Phase 2 (ADRs reference) |
| **Phase 4** | Benchmark script + first run | Existing test infrastructure |
| **Phase 5** | Demo script + interview Q&A | All prior phases |

---

## Exit Criteria

- [ ] `/dashboard` page shows live metrics with 6 working charts/components
- [ ] 5 ADRs written, indexed in `docs/adrs/README.md`
- [ ] ARCHITECTURE.md updated with 5 new Mermaid diagrams
- [ ] `scripts/benchmark.py` produces reproducible latency numbers
- [ ] `docs/demo/interview-demo.md` covers 8-step walkthrough
- [ ] All tests still pass (81+)
