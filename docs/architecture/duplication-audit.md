# Architecture Duplication Audit

Date: 2026-07-06

Scope: Boundary cleanup across the first architecture pass and follow-up tool
chain verification. This pass documents duplicated or drifting architecture
boundaries and fixes low-risk event-catalog, startup, config namespace, and tool
namespace drift. It does not rewrite LangGraph, memory, provider registration,
or frontend behavior.

## Current Architecture Map

Observed runtime path:

```text
frontend
  -> Socket.IO / REST
  -> animetta.core.socketio_server
  -> animetta.orchestration.server.websocket.create_server()
  -> WebSocketServer.setup_routes()
  -> RouteHandlers
  -> SessionManager
  -> LangGraphOrchestrator
  -> graph nodes
  -> services / memory / avatar / tools / tracing / inspection
```

Primary boundaries:

| Boundary | Current source of responsibility |
| --- | --- |
| CLI/runtime entrypoint | `src/animetta/core/socketio_server.py` |
| ASGI server construction | `src/animetta/orchestration/server/websocket.py` |
| Socket.IO event registration | `src/animetta/orchestration/server/routes.py` |
| Event catalog | `config/socket-events.json` |
| Backend event lookup | `src/animetta/orchestration/socket_events.py` |
| Frontend event lookup | `frontend/src/constants/socket-events.ts` |
| Shared engine pool | `src/animetta/core/service_pool.py` |
| Provider registry | `src/animetta/config/core/registry.py` |
| Runtime config reload | `src/animetta/config/runtime_reload.py` |
| Tracing bootstrap | `src/animetta/tracing/bootstrap.py` |
| Inspection scheduler | `src/animetta/inspection/scheduler.py` |

## Confirmed Duplicates

### Socket.IO registration fallbacks

`routes.py` used `EVENTS.get(...).get(...).get("name", "module:action")`
for most registered inbound events, while `config/socket-events.json` is
documented as the source of truth. This duplicated every registered event name
and allowed the backend to drift silently if JSON entries were missing.

### Missing Minecraft command catalog entry

`routes.py` registered `minecraft:command` directly, but the event did not
exist in `config/socket-events.json` or `frontend/src/constants/socket-events.ts`.
The handler already existed, so this was catalog drift, not a new public event.

### Duplicate tracing bootstrap ownership

`core/socketio_server.py:get_asgi_app()` imported and called
`init_tracing()` before delegating to
`orchestration.server.websocket.create_server()`. The server factory already
calls `WebSocketServer.setup_tracing()`, so tracing ownership was split across
two startup layers.

### Removed config namespace references

The current config package lives at `src/animetta/config/`, but package root
lazy exports and several tests still referenced the removed
`animetta.core.config` namespace. The old directory no longer exists, so those
references were stale migration residue rather than a compatibility layer.

### Removed tools namespace and external package drift

The current tools package lives at `src/animetta/tools/`, but several tool and
ToolManager tests still referenced the removed `animetta.core.tools` namespace
or the old `ToolManager.core.tools` wrapper shape. The MCP bridge also read
`ListToolsResult.core.tools`, while the current MCP SDK exposes `tools`
directly. `web_search` had the same kind of external package drift for
DuckDuckGo fallback, importing `langchain_community.core.tools` instead of the
current `langchain_community.tools`.

## Fixed In This Patch

| Fix | Files |
| --- | --- |
| Added `event_name(module, action)` backend accessor that fails fast when an event is absent from the catalog. | `src/animetta/orchestration/socket_events.py` |
| Replaced inbound route-registration fallback strings with `event_name(...)`. | `src/animetta/orchestration/server/routes.py` |
| Added `minecraft.command` to the shared JSON catalog and frontend constants. | `config/socket-events.json`, `frontend/src/constants/socket-events.ts` |
| Added focused tests for configured lookup, missing lookup, and the Minecraft command catalog entry. | `tests/orchestration/test_socket_events.py` |
| Delegated tracing bootstrap solely to `create_server()` and added an entrypoint boundary test. | `src/animetta/core/socketio_server.py`, `tests/core/test_socketio_server.py` |
| Moved stale `animetta.core.config` references to `animetta.config` without reintroducing the deleted namespace. | `src/animetta/__init__.py`, config/service tests |
| Updated startup docs and stale CLI prompt text to the current entrypoint. | `src/animetta/core/AGENTS.md`, `src/animetta/utils/auto_config.py` |
| Fixed MCP tool discovery to use the current SDK `ListToolsResult.tools` field and added a regression test. | `src/animetta/tools/mcp_bridge.py`, `tests/tools/test_mcp_bridge.py` |
| Fixed DuckDuckGo fallback import to the current LangChain Community tools namespace and added a no-network fallback test. | `src/animetta/tools/base.py`, `tests/tools/test_base.py` |
| Moved stale tools tests from `animetta.core.tools` / `*.core.tools` wrapper expectations to the current `animetta.tools` and flat `ToolManager` shape. | `tests/tools/`, `tests/orchestration/graph/test_tool_manager.py` |

Behavior preserved:

- Existing Socket.IO event names are unchanged.
- `python -m animetta.core.socketio_server` remains the runtime entrypoint.
- `minecraft:command` remains registered, now through the shared catalog.
- Config models remain exported from package root lazy attributes, now through
  the current `animetta.config` package.
- MCP servers that return tools through the current SDK shape now populate
  LangChain tools instead of being silently treated as empty.
- `web_search` still prefers Tavily when configured and now reaches its
  DuckDuckGo fallback when Tavily is absent.

## Left For Later

### Entrypoint and runtime setup

`core/socketio_server.py` is a compatibility/runtime entrypoint that delegates
server construction to `orchestration.server.websocket.create_server()`. It also
owns runtime-only concerns:

- config initialization
- uvicorn startup
- frontend SPA middleware wrapping
- file logging
- Redis checkpointer setup
- background model warmup
- service prewarm
- inspection scheduler startup

`WebSocketServer.create_server()` owns tracing, routes, and lifecycle setup.
Moving the remaining runtime-only concerns would touch startup behavior and
should be a separate Phase 2 change with integration coverage.

### Health, inspection, and tracing

Health and inspection concerns are split across:

- lightweight ASGI route probes in `scripts/route_smoke.py`
- health gate orchestration in `scripts/health_check.py`
- inspection checks under `src/animetta/inspection/`
- tracing bootstrap in `src/animetta/tracing/bootstrap.py`
- `/metrics` setup inside `WebSocketServer`

No literal duplicate was safe to remove in Phase 1. The current split should be
documented more explicitly before consolidation.

### Provider and config construction

Provider creation mostly flows through `ProviderRegistry` and `ServicePool`, but
there are still category-specific factory helpers and several runtime seams that
call `AppConfig.load()` directly. This is expected today because handlers,
runtime reload, and tool setup need different config timing. Consolidating this
should wait until the service-container boundary is designed explicitly.

### Legacy documentation drift

Some existing architecture docs still mention older FastAPI/EventBus/Pipeline
terms. This audit avoids broad doc rewrites, but Phase 2 should align docs with
the current Starlette + Socket.IO ASGI + LangGraph architecture.

## Recommended Phase 2 Tasks

1. Define a single runtime bootstrap object for config, tracing, logging,
   checkpointer setup, warmup, and inspection scheduler startup.
2. Move health/inspection/tracing boundary documentation into one source of
   truth, then consolidate only the parts with duplicate executable logic.
3. Add a generated or schema-checked Socket.IO event API for both Python and
   TypeScript so all event names come from `config/socket-events.json`.
4. Audit direct `AppConfig.load()` calls and classify them as bootstrap,
   request-time fallback, reload, or test utility.
5. Update stale architecture docs after runtime boundaries are settled.
