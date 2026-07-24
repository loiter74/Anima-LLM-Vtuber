# Animetta — Current Architecture (2026-07-25 audit)

> Snapshot taken on branch `audit/nightly-refactor-2026-07-25`.
> This document describes the **actual** runtime architecture as verified by
> reading source on 2026-07-25, and supersedes the older
> `docs/architecture/overview.md` (which is still accurate at the C4 level but
> does not cover the two-pass dialogue graph, the chat-contract transport
> layer, or the desktop-transport probe gap documented here).
>
> Source-of-truth docs that this file references rather than duplicates:
> - C4 + sequence diagrams: `docs/architecture/overview.md`
> - Boundary / duplication history: `docs/architecture/duplication-audit.md`
> - Design decisions: `docs/adrs/` (13 ADRs)
> - Socket.IO event catalog: `config/socket-events.json` + `src/animetta/orchestration/socket_events.py`

---

## 1. System context (one paragraph)

Animetta is a VTuber/companion engine. A Vue 3 + Electron frontend talks to a
Python backend over Socket.IO. The backend is a **Starlette + Socket.IO ASGI**
app that hosts a **LangGraph** state machine. Each turn the graph runs
ASR → (persona + memory + personality + drift guard) → LLM → (optional tool
loop) → TTS → emotion → output, emitting streaming Socket.IO events to the
frontend, which drives a Live2D avatar. Services (LLM / ASR / TTS / VAD /
Live2D / memory) are swappable plugins registered through `@ProviderRegistry`.

---

## 2. Runtime call chain — text input → output

Verified path for a canonical `chat:text` event:

```
Frontend (Vue/Electron)
  │  emits "chat:text" {text, message_id, conversation_id, task_id, turn_id, ...}
  ▼
Socket.IO ASGI (src/animetta/core/socketio_server.py:get_asgi_app)
  │  uvicorn factory; loads config, file logging, redis checkpointer,
  │  model warmup, service prewarm, inspection scheduler (all background tasks)
  ▼
WebSocketServer (src/animetta/orchestration/server/websocket.py)
  │  owns: sio, SessionManager, RouteHandlers, stats_api, /metrics, /health
  ▼
register_routes() (src/animetta/orchestration/server/routes.py:378)
  │  sio.on(event_name("chat","text"), text_adapter)   ← routes.py:416
  ▼
text_adapter → ChatHandlers.on_text_event (chat_handlers.py:121)
  │  1. is_probe_message(data)  → drop inspection/health/ping   [message_filter.py]
  │  2. normalize_chat_command(event, data) → ChatTurnCommand   [chat_contracts.py]
  │     (pydantic validator _reject_unfiltered_probe is fail-closed)
  │  3. per-conversation asyncio.Lock
  ▼
ChatHandlers._process_text_command (chat_handlers.py:158)
  │  - optional meme short-circuit (parse_meme_invocation)
  │  - admin._get_or_create_orchestrator(sid)
  ▼
SessionManager.get_or_create_orchestrator (session.py:134)
  │  - get_or_create_context(sid) → ServiceContext (LLM/TTS/ASR engines,
  │    from ServicePool shared pool when available)
  │  - LangGraphOrchestrator.create(session_id, ctx, sio, ...)
  ▼
LangGraphOrchestrator.process_text (orchestrator.py:157)
  │  - create_initial_state(...) → AgentState (TypedDict)
  │  - _run_graph → graph.ainvoke(state, config=RunnableConfig)
  ▼
LangGraph state graph (orchestration/graph/builder.py: create_default_graph)
  │  Two topologies coexist:
  │
  │  (A) LEGACY DIRECT GRAPH (default, non-golden profile):
  │      START → personality_node → llm_node ──┬→ tts_node → emotion_node → output_node → END
  │                                            └→ (tool_calls) → tool_node → llm_node
  │
  │  (B) GOLDEN TWO-PASS GRAPH (runtime_profile=="golden"):
  │      START → personality_node → reasoner_node → anima_composer_node →
  │              response_guard_node → conversation_finalizer_node → tts_node → output_node
  │      (uses services/dialogue/ Reasoner + AnimaComposer + select_final_response)
  ▼
output_node (output_node.py)
  │  - emits chat:sentence / chat:expression / chat:audio_with_expression via ChatDelivery
  │  - stores turn to memory (encode) when persistence policy allows
  │  - records observation trace (start/finish)
  ▼
Frontend renders text + animates Live2D
```

### Nodes and their I/O

| Node | File | Input state | Output state | Responsibility |
|---|---|---|---|---|
| `personality_node` | `personality_node.py` | `metadata`, `channel_id`, `conversation_emotion`, persona config | `personality_mode`, `personality_mood`, `system_prompt`, `metadata.roleplay_correction`, MBTI/knowledge bounds | Picks streaming vs default mode, mood overlay, **detects previous-turn drift** |
| `llm_node` | `llm_node.py` | `user_text`, `messages`, `persona`, RAG context | `response_text`, `response_chunks`, `tool_calls`, `affinity` | LLM call (streaming or tool-calling), strips thinking blocks / emotion tags, parses `[affinity:N]`, enforces verbal tics |
| `reasoner_node` | `dialogue_nodes.py:44` | `user_text`, `system_prompt`, session window | `turn_scratch.reasoner` | Golden-path first LLM pass (Reasoner service) |
| `anima_composer_node` | `dialogue_nodes.py:81` | reasoner scratch, mood/affinity | `turn_scratch.composer` | Golden-path second LLM pass (character composer) |
| `response_guard_node` | `dialogue_nodes.py:114` | reasoner+composer scratch | `response_text` | Picks final reply via `select_final_response` |
| `conversation_finalizer_node` | `dialogue_nodes.py:144` | response + persistence policy | commits session window + long-term memory | Persistence gate, **refuses probes** |
| `tool_node` | `tool_node.py` | `tool_calls` | `tool_results` | Built-in / MCP / LangChain tools via `ToolManager` |
| `tts_node` | `tts_node.py` | `response_text`, `emotion` | `tts_audio`, streaming audio events | TTS synthesis + emotion-tag/emoji cleanup, interrupt-aware |
| `emotion_node` | `emotion_node.py` | `response_text` | `emotion` | Keyword + LLM-based sentiment → 6 base emotions |
| `output_node` | `output_node.py` | all state | Socket.IO events + memory store | Delivery + memory persistence + trace finish |

---

## 3. Module responsibility map

| Module | Path | Responsibility | Key dependencies | State storage |
|---|---|---|---|---|
| **Entry / bootstrap** | `core/socketio_server.py` | uvicorn factory, config init, file logging, redis checkpointer, warmup/prewarm/inspection background tasks | `config.manifest`, `inspection.scheduler`, `orchestration.server.websocket` | module globals `global_config`, `_server`, `_INIT_DONE` |
| **ASGI server** | `orchestration/server/websocket.py` (`WebSocketServer`, 506 lines) | assembles sio + routes + stats_api + /metrics + /health + lifecycle | `routes.register_routes`, `session.SessionManager`, `stats_api`, `tracing.bootstrap` | instance attrs |
| **Route facade** | `orchestration/server/routes.py` (`RouteHandlers`) | thin delegation; `register_routes()` binds `sio.on(...)` | 11 handler modules under `server/handlers/` | — |
| **Chat transport** | `orchestration/chat_contracts.py`, `chat_delivery.py` | pydantic `ChatTurnCommand`, `ChatErrorPayload`, legacy/canonical event normalization, ack delivery | `socket_events.resolve_socket_event` | — |
| **Session mgmt** | `orchestration/server/session.py` (`SessionManager`) | per-sid `ServiceContext` + `LangGraphOrchestrator` + audio processor; owns the real orchestrator registry | `core.service_pool.ServicePool`, `ServiceContext` | `self.contexts`, `self.orchestrators`, `self.audio_processors` (per-instance dicts) |
| **Graph** | `orchestration/graph/` | LangGraph builder + nodes + orchestrator | `services.*`, `memory.v2`, `tools` | `LangGraphOrchestrator._langgraph_config` (per-instance) |
| **Services** | `services/{llm,asr,tts,vad,live2d,dialogue,humor,effects,meme,bilibili,singing,vc,...}` | provider implementations behind interfaces | external SDKs, `config.providers.*` | per-engine state |
| **Memory V2** | `memory/v2/` | atom-based: Chroma vector + SQLite FTS5 + markdown wiki; `LivingMemorySystem` | chromadb, sqlite3 | `memory_db/chroma_v2`, `memory_db/living_memory.sqlite`, `data/` markdown |
| **Config** | `config/` | `EffectiveConfig` manifest (Pydantic), personas, providers, runtime reload | pydantic v2, yaml | `config/animetta.yaml`, `config/personas/*.yaml` |
| **Tools** | `tools/` | `@tool` built-ins, MCP bridge, LangChain tools, Minecraft bot (Node.js hybrid) | langchain, mcp | `data/mc_skills.db` |
| **Inspection** | `inspection/` | scheduled background health/conversation/pipeline checks → StatsStore + notifier | Socket.IO client (external), `stats_api` | `data/stats.db` (`inspection_reports`) |
| **Tracing** | `tracing/bootstrap.py`, `observability/` | OpenTelemetry + Prometheus + Langfuse + StatsStore | opentelemetry, prometheus_client | `data/stats.db`, remote OTLP |
| **Readiness / preflight** | `core/readiness.py`, `core/golden_preflight.py`, `core/component_readiness.py` | boot-time + on-demand readiness evidence | services, config | evidence JSON under `artifacts/` |
| **Avatar** | `avatar/` | Live2D emotion/expression/viseme analysis | numpy | — |
| **Notifier** | `notifier/` | Discord / Feishu / Email alert channels | httpx | — |

---

## 4. State storage locations

| Store | Tech | Path / handle | Written by | Read by |
|---|---|---|---|---|
| Conversation checkpoint | LangGraph `MemorySaver` (default) or `AsyncRedisSaver` (`--redis-url`) | in-memory / redis | orchestrator graph | graph resume |
| Short-term window | `ConversationSessionState` (in-process) | orchestrator instance | `conversation_finalizer_node` / `llm_node` | next-turn prompt |
| Long-term memory | Chroma v2 + SQLite FTS5 | `memory_db/chroma_v2`, `memory_db/living_memory.sqlite` | `LivingMemorySystem.encode` | `_retrieve_memory_context` (RAG) |
| Wiki knowledge | Markdown | `data/` + persona `memories/` | memory organize | hybrid search |
| Stats / inspection | SQLite | `data/stats.db` | `StatsStore`, inspection reporter | `/api/stats/*`, `/api/stats/inspection/latest` |
| Minecraft skills | SQLite | `data/mc_skills.db` | MC bot | Voyager runtime |
| Logs | loguru file sink | `logs/animetta.log` (rotated daily, 7-day retention) | `socketio_server.get_asgi_app` | Loki (optional) |
| User settings | YAML | project root `.user_settings.yaml` | `UserSettings` | log-level apply |

---

## 5. LLM / TTS / Live2D / WebSocket connection map

```
                         ┌──────────────────────────┐
   Socket.IO client ───► │  AsyncServer (python-    │
   (frontend / Electron  │  socketio, asgi mode)    │
    / inspection probe)  └────────────┬─────────────┘
                                     │ sio.on(event_name(...))
                                     ▼
                         register_routes()  ← config/socket-events.json
                                     │
                                     ▼
                         RouteHandlers → ChatHandlers / Live2DHandlers /
                                         BilibiliHandlers / PersonaHandlers /
                                         ConfigHandlers / MemoryHandlers /
                                         MinecraftHandlers / SingingHandlers /
                                         MemeHandlers / LifecycleHandlers
                                     │
                                     ▼
                         SessionManager ──► ServiceContext ──► ServicePool (shared)
                                                         │              ├─ LLM engine (deepseek/glm/openai/ollama/mock)
                                                         │              ├─ TTS engine (edge/mimo/qwen3/gpt-sovITS/glm/...)
                                                         │              ├─ ASR engine (whisper/glm/mock)
                                                         │              └─ VAD engine (silero)
                                                         ▼
                         LangGraphOrchestrator ──► CompiledAgentGraph
                                                         │
                                          ┌──────────────┼───────────────┐
                                          ▼              ▼               ▼
                                   memory.v2 recall   LLM provider    TTS provider
                                   (Chroma+FTS5)      (HTTP/stream)   (HTTP/stream)
                                                          │
                                                          ▼
                                                  tools (built-in / MCP / MC bot)
```

**Live2D**: `tts_node` emits `chat:audio_with_expression` + `chat:expression`.
`emotion_node` produces the emotion tag. The frontend maps emotion → Live2D
parameters (pixi-live2d-display). `Live2DManager` (`server/live2d.py`) owns the
action queue broadcast to desktop clients; `avatar/` does the server-side
emotion/viseme analysis.

**Inspection probe path** (defense in depth, verified 2026-07-25):
`inspection/checks/pipeline.py` connects as an external Socket.IO client and
emits `chat:text` with `{"text": "[inspection] ping", "is_inspection": True}`.
This is dropped at **three** layers:
1. `ChatHandlers.on_text_event` → `is_probe_message(data)` (`chat_handlers.py:123`)
2. `ChatTurnCommand._reject_unfiltered_probe` pydantic validator (`chat_contracts.py:160`)
3. `reasoner_node` / `conversation_finalizer_node` re-check `metadata.is_inspection` (`dialogue_nodes.py:46,154`)

> ⚠️ **Gap (see audit-report P0-1)**: the **`desktop.chat_message`** event
> (`routes.py:438` → `live2d_handlers.on_desktop_chat_message:99`) calls
> `orchestrator.process_text` **directly**, bypassing `is_probe_message`,
> `normalize_chat_command`, and never sets `is_inspection` metadata — so the
> in-graph Layer 3 guards do not fire either. Any Socket.IO client that emits
> `desktop.chat_message` can send probe-shaped or drift-inducing text straight
> to the LLM.

---

## 6. Configuration layering

```
config/animetta.yaml          ← canonical manifest: profiles, provider map, runtime policy
config/personas/*.yaml        ← character definitions (name, role, personality, MBTI, knowledge bounds, voice)
config/tools.yaml             ← tool_settings + MCP servers
config/bilibili.yaml          ← Bilibili livestream config
config/singing.yaml           ← singing pipeline config
config/socket-events.json     ← Socket.IO event catalog (source of truth for event names)
.env                          ← ANIMETTA_PROFILE + provider API keys + endpoints ONLY
.user_settings.yaml           ← runtime log-level preference
```

`load_effective_config()` (`config/manifest.py`) resolves the profile,
expands env vars (with secret redaction in logs), and produces a single
immutable-ish `EffectiveConfig` Pydantic object. Runtime reload is exposed via
`POST /api/config/reload` and `config/runtime_reload.py` (computes a diff and
applies it to live contexts).

---

## 7. Two coexisting dialogue topologies

This is the most important architectural fact missed by the older overview:

- **Default (legacy direct) graph** — used in `development` / `production` /
  `test` / `smoke` profiles. `llm_node` does everything: streaming, tool calls,
  thinking-block stripping, affinity parsing, verbal-tic enforcement.
- **Golden two-pass graph** — used when `system.runtime_profile == "golden"`.
  Replaces `llm_node` with `reasoner_node → anima_composer_node →
  response_guard_node → conversation_finalizer_node`, backed by
  `services/dialogue/` (`Reasoner`, `AnimaComposer`,
  `select_final_response`). Tools are force-disabled in golden mode
  (`session.py:168`).

Both share `personality_node`, `tts_node`, `emotion_node`, `output_node`. The
graph is selected at build time in `builder.create_default_graph(golden_profile=...)`.

---

## 8. Persona / memory / message-filter / agent-loop boundaries

| Boundary | Owner | Consumers | Cleared? |
|---|---|---|---|
| **Persona config** | `config/persona/` + `EffectiveConfig.get_persona()` | `personality_node`, `_get_persona_dict`, prompt pipeline `sources.py` | ✅ single source |
| **Persona drift detection** | `prompting/roleplay_guard.detect_drift` + `personality_node._detect_previous_turn_drift` | injects `metadata.roleplay_correction` → `RoleplayGuardPromptSource` next turn | ✅ but `detect_drift` is only asserted in `golden_soak`; no unit test for the injection loop |
| **Memory RAG** | `memory.v2.LivingMemorySystem.recall` via `MemoryMiddleware` | `llm_node._retrieve_memory_context` / golden `reasoner_node` (prompt pipeline) | ✅ |
| **Message ingress filter** | `core/message_filter.is_probe_message` | `ChatHandlers.on_text_event`, `on_text_input` | ✅ for chat path; ❌ for desktop path (P0-1) |
| **Agent loop** | LangGraph conditional edges (`llm_node ↔ tool_node`) | `ToolManager`, `tools/mcp_bridge.py` | ✅ |
| **Persistence gate** | `graph/persistence_policy.decide_persistence` + `long_term_memory_mode` config | `conversation_finalizer_node`, `output_node._store_conversation_to_memory` | ✅ |

`BLEED_MARKERS` (`message_filter.py:47`) is a documented telemetry surface
with **zero runtime consumers** — only a test references it.

---

## 9. Known hotspots (carried forward from prior audits)

- `orchestration/server/routes.py` — now a thin facade (~488 lines, was 446); still the single registration site.
- `orchestration/server/websocket.py` — `WebSocketServer.__init__` is 192 lines and owns too many concerns (candidate for a bootstrap object, deferred to Phase 2 per `duplication-audit.md`).
- `core/golden_preflight.py:run_golden_preflight` — 303-line single function.
- `orchestration/graph/output_node.py:output_node` — 239-line node function.
- `core/service_context.py:ServiceContext` — 784-line class.

---

## 10. What this audit changed vs. the prior overview

| Topic | Prior `overview.md` | This document |
|---|---|---|
| Graph topology | Single direct graph shown | Documents both default and golden two-pass graphs |
| Ingress filtering | Not mentioned | Documents the 3-layer probe containment + the desktop gap |
| Chat transport | Not mentioned | Documents `chat_contracts` / `chat_delivery` transport normalization |
| Drift guard | Not mentioned | Documents `roleplay_guard` + `personality_node` correction loop |
| Orchestrator registry | Implied single | Clarifies `SessionManager.orchestrators` is the real registry; `LangGraphOrchestrator._instances` is dead (see audit) |
