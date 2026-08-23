# Animetta Module Map

This document defines the production module ownership and dependency direction established
by [ADR-013](../adrs/ADR-013-unidirectional-module-boundaries.md). It complements the
runtime diagrams in [overview.md](overview.md).

## Dependency Direction

```text
core process bootstrap
  -> orchestration/server composition
      -> runtime ownership + orchestration/graph
          -> services | memory/v2 | avatar | tools
      -> config | observability ports | inspection

frontend app/views -> components/composables/stores -> services -> shared
frontend live -------------------------------------> review + shared
```

Arrows mean "may depend on". Reverse arrows are forbidden. Cross-cutting behavior is
expressed as a protocol owned by the consumer and implemented at the composition boundary.

## Backend Modules

| Module | Owns | Must not own |
|---|---|---|
| `core` | Process bootstrap and one-release import facades | Conversation policy, provider/session lifetime, Socket route behavior |
| `runtime` | Application-owned provider pool, session context, model loading, checkpointing, shared-memory attachment and readiness | Socket route policy or UI-facing response shaping |
| `orchestration/server` | Starlette/Socket.IO adapters, authentication, rate limits, sessions, route registration | Provider construction, persistence schemas, domain decisions |
| `orchestration/graph` | AgentState, LangGraph topology, thin state-transforming nodes | Transport-specific emission, filesystem processing, concrete service lifecycle |
| `services` | Provider interfaces/factories and cohesive feature services such as dialogue, Bilibili, singing and programs | Process bootstrap or LangGraph state |
| `memory/v2` | Atom lifecycle, hybrid retrieval and memory persistence ports/adapters | Socket handlers or session construction |
| `avatar` | Emotion analysis, parameter mapping and performance contracts | Frontend rendering or graph routing |
| `tools` | Product tools, MCP adapters and the Minecraft public gateway | Whole-application composition |
| `config` | Frozen schemas, manifest resolution, public snapshots and hashes | Runtime service mutation or readiness probing |
| `observability` | Observation domain, ports, ledger and mirrors | Imports of concrete product features |
| `inspection` | Read-only health checks over injected ports | Runtime orchestration or feature control |

## Frontend Modules

| Module | Owns | Dependency rule |
|---|---|---|
| `shared` | Socket contracts, transport ports, audio/Live2D primitives | External packages and `shared` only |
| `services` | Browser resource adapters: Socket instance, IndexedDB messages and resumable command tasks | `shared`, neutral constants and data types |
| `stores` | Domain-facing reactive state | `services`, contracts and data types; never composables |
| `composables` | Vue lifecycle coordination over stores and services | May compose stores/services, but owns no persistence singleton |
| `components` / `views` | Dashboard presentation and feature composition | Composables, stores, services and shared modules |
| `live` | The non-Vue `/live.html` controller and view | Live-owned code, review plugins and shared foundations; never Dashboard components/stores |
| `review` | Review-stage runtime, deterministic fixtures and review utilities | Shared contracts; never imports `live` internals |

## Runtime Ownership

- One application owns one provider pool.
- LLM, TTS and ASR engines are shared and closed exactly once by the application.
- VAD, audio processor, memory attachment and emotion state are session-owned.
- Starlette lifespan is the authoritative asynchronous startup/shutdown boundary.
- LangGraph state contains serializable conversation data; runtime dependencies live in one
  typed runtime object supplied through `RunnableConfig`.

## Compatibility Window

Legacy Python import facades and Socket aliases are accepted for one released version.
Protocol-v2 clients use canonical `module:action` event names. Compatibility modules are
terminal adapters: canonical production modules never import them.

The current Python facades include the former `animetta.core` runtime modules,
`animetta.config.runtime_reload` and `animetta.tools.minecraft.showcase.live`. Their
canonical replacements live in `animetta.runtime`, `animetta.config.runtime_reloader` plus
`animetta.services.runtime_config`, and `animetta.acceptance.minecraft_showcase`.

Frontend compatibility facades keep the old message-store, command-task and Socket payload
type imports working for one release. New code imports `frontend/src/services` and
`frontend/src/shared/contracts` directly.
