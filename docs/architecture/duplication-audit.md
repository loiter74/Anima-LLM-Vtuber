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

### Script and integration-test event drift

`scripts/validate-events.py` only checked backend `sio.emit(...)` calls under
`src/animetta`, so helper scripts and integration tests could keep using
removed event names such as `text_input`, `raw_audio_data`, `sentence`,
`audio_with_expression`, `expression`, and `transcript` without failing the
event gate. The same gate also only checked that the frontend constants file
referenced every catalog entry; it did not reject hard-coded frontend
`socket.emit(...)` / `socket.on(...)` literals. Those callers no longer matched
the catalog-backed runtime events.

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

### LLM adapter config shape drift

`create_chat_model_from_service()` checked for the current `llm_service.config`
attribute but then read model metadata from the legacy `llm_service.core.config`
shape. Current LLM providers expose their configuration directly, so LangChain
adapter construction could lose the model name or fail when only the current
provider shape was present.

### Health gate interpreter drift

`scripts/health_check.py` selected an existing repository `.venv` before
checking whether that interpreter could import the modules required by the
health gates. A stale or partial `.venv` caused backend tests, secret scanning,
and route smoke probes to fail even when the active Codex interpreter had the
needed test/runtime packages.

### Optional VC provider import drift

`animetta.services.vc.__init__` eagerly imported the RVC provider, which forced
optional audio dependencies such as `soundfile` to exist even when callers only
needed `VCFactory` or `MockVC`. This broke the mock/factory path and made the VC
package import depend on a heavy provider that should be loaded on demand.

### Stale `core.config` test shape

Several tests still asserted removed wrapper shapes such as
`ServiceContext.core.config`, `WebSocketServer.core.config`,
`PositionBasedStrategy.core.config`, and `VisemeLipSync.core.config`. The
runtime objects now expose their configuration directly via `config`, so the
tests were preserving a deleted boundary rather than verifying current behavior.

### Server handler dependency drift after boundary split

Several event handlers had been split out of `routes.py` but still depended on
names or object shapes that were not carried across the new boundary.
`ConfigHandlers` referenced translation/config/logger dependencies without
importing them, and Bilibili/persona handlers still reached through removed
`service_context.core.config` / `ctx.core.config` wrappers on runtime paths.
The config response path also drifted after the split: `config:get` read
personas from `src/animetta/config/personas` instead of the project
`config/personas` directory and called the removed `Live2DConfig.load()`
entrypoint instead of the current `get_live2d_config()`. The enhanced persona
builder had the same root-directory drift and resolved default personas under
`src/config/personas`. The Socket.IO runtime entrypoint also mixed path
ownership: `.env`, logs, and frontend serving used the project root, but
`UserSettings` was initialized with `src/`, so runtime log-level changes were
persisted to `src/.user_settings.yaml` instead of the project root.

### Duplicate Bilibili configuration entrypoint

`AppConfig` already loads the optional Bilibili danmaku settings from
`config/bilibili.yaml`, but `WebSocketServer` still tried to read a top-level
`bilibili` key from `config/config.yaml` by hand during route setup. This
created two competing configuration entrypoints and prevented the parsed
runtime config object from controlling Bilibili auto-start.

### ServicePool failure cleanup ownership drift

`ServicePool.init()` uses a temporary `ServiceContext` to initialize pooled
LLM/TTS/ASR engines, then keeps those shared engines alive on the success path.
`ServiceContext.close()` therefore intentionally does not close those shared
engines. The failure path still relied on `ctx.close()` to "close whatever was
opened", so a partially initialized LLM/TTS/ASR engine could leak if
`load_from_config()` failed after assigning it to the context.

### Memory/Wiki handler split residue

`routes.py` is documented as a thin facade after the server handler split, but
`memory:organize` and `memory:list_pages` still kept their V2 memory business
logic in the facade. Those methods also loaded config directly instead of using
the shared handler context boundary. At the same boundary, `RouteHandlers`
copied `global_config` and `user_settings` from `BaseSocketHandler` as plain
attributes, so backward-compatible direct assignment could diverge from the
state seen by extracted handlers.

### Duplicated server handler config fallback

After `BaseSocketHandler` gained the shared `get_active_config()` helper,
`ConfigHandlers.on_get_config()` still kept its own
`self.global_config or AppConfig.load()` fallback. That left two server-handler
config fallback entrypoints and made future handler moves more likely to drift.

### Duplicated persona catalog path and listing logic

Persona loading, enhanced persona prompt loading, `config:get`, and
`persona:list` each carried their own project `config/personas` path or `*.yaml`
listing logic. That made the persona catalog boundary drift-prone and left
server handlers responsible for filesystem details already owned by config.
After the first catalog cleanup, `persona:list` still reloaded the active
persona by name to extract MBTI data even when `AppConfig` already held the
current cached persona.

### Persona handler config logging leak

`PersonaHandlers.global_config` logged full config objects while bridging config
state between the shared route handler base and the extracted persona handler.
That made the server-handler boundary noisy and could leak provider/API-key
details through object `repr()` output in runtime logs.

### Config expansion debug logging leak

`AppConfig._apply_env_expansion()` logged full provider config dumps before and
after environment expansion, and `expand_env_vars()` logged API-key prefixes
for GLM. This made debug logs a second copy of provider secrets after
environment expansion.

### Tool config logging leak

`SessionManager` logged full tool configuration values while creating
orchestrators and while loading `config/tools.yaml`. Tool settings may include
MCP credentials or provider tokens, so INFO logs should only expose routing
metadata such as enabled state and key names.

### Direct config load boundary classification

The remaining production `AppConfig.load()` calls are now classified by timing:

- `core/socketio_server.py` is bootstrap-time runtime config initialization.
- `config/runtime_reload.py` is an explicit runtime reload path.
- `BaseSocketHandler.get_active_config()` is the single request-time fallback
  for handlers without an injected `global_config`.

No additional production call site currently bypasses those categories.

### Inspection check drift from runtime boundaries

The scheduled conversation inspection still expected legacy bare output events
(`sentence`, `expression`, `audio_with_expression`) while current Socket.IO
events are catalog-backed (`chat:*`). The same check also sent
`is_inspection=True`, which the current ingress filter correctly drops before
LLM dispatch, so expecting LLM/TTS output was impossible. Separately,
`data_consistency` checked `logs/anima.log` after the runtime entrypoint moved
file logging to `logs/animetta.log` and treated the absence of recent user
conversation traces as a consistency failure, even when the idle StatsStore was
reachable.

### Health endpoint status-code drift

`/health` returned JSON bodies with `status: "degraded"` or `status: "error"`
when component checks failed or the health-check runner itself crashed, but the
HTTP response still defaulted to 200. That weakened the runtime contract used by
Docker and external probes, because unhealthy states could look HTTP-healthy
unless the response body was also parsed.

### Inspection latest API documentation drift

`GET /api/stats/inspection/latest` returns the latest persisted
`inspection_reports` row from `StatsStore`, including `run_id`, timestamps,
`overall_ok`, and deserialized per-check results. The reference API example
still documented an older synthetic `{timestamp, status, checks}` shape, and the
stats API tests did not cover this route.

### Metrics route smoke coverage gap

`WebSocketServer` mounts `/metrics` when `prometheus-client` is available, but
`scripts/route_smoke.py` only checked singing media routes. That left the
runtime observability endpoint outside the lightweight ASGI route gate even
though the integration tests and Docker protocol rely on route probes for early
startup regressions.

### Stats API route smoke coverage gap

The stats API had endpoint-level tests, but `scripts/route_smoke.py` did not
probe the stats routes through the assembled lightweight `WebSocketServer`
ASGI app. A route registration or mount regression could therefore pass the
fast health gate while breaking `/api/stats/overview`, `/api/stats/nodes`,
`/api/stats/traces`, or trace detail/tree routing in the assembled app.

### Runtime config reload route smoke coverage gap

`WebSocketServer` mounts `POST /api/config/reload`, but the lightweight route
smoke gate only exercised GET endpoints. The reload implementation already had
unit coverage for applying reloaded config to active contexts, but the assembled
HTTP route itself could drift out of the ASGI route table without failing the
fast health gate.

### Duplicate model-status payload shape

The backend `ModelLoadingManager` emits `system:model_status` with
`{service, name, status, error?}`, and the active frontend store consumes that
shape through `frontend/src/types/model-loading.ts`. The socket event constants
file still exposed an unused `SystemModelStatusPayload`, and
`config/socket-events.json` still documented the older
`{model_name, status, progress}` payload, leaving the catalog and frontend
contract incompatible with the runtime event.

### Translation configure payload drift

`translation:configure` documented both `enabled` and `target_language` as
required fields, while the frontend settings panel only sent
`target_language` when the language changed. The backend also ignored
`enabled`, so the subtitle enable toggle stayed local-only and the shared
translation state had no runtime update path for that field.

### Persona card current-persona drift

`PersonaCard` displayed the first available persona instead of the active
runtime persona. The frontend personality store only tracked
`availablePersonas`, while `persona:list` returned no explicit current-persona
field. A backend using a non-first configured persona could therefore show a
different persona in the drawer than the active runtime config and MBTI data.

### Minecraft viewer error state drift

The backend `minecraft:viewer_status` event can emit `{status: "error",
error: ...}` when spectate fails or the bot is not running. The frontend store
declared the payload as supporting `error`, but `viewerStatus` could not hold
that state and the handler intentionally left the previous state unchanged.
Manual spectate failures could therefore leave the settings panel showing stale
`waiting`, `joined`, or `left` state.

### Chat interrupt event chain gap

The backend registers `chat:interrupt` and `ChatHandlers.on_interrupt_signal`
sets the shared interrupt handler before emitting `chat:stop_audio` and a
control event. The frontend interrupt button called `sendInterrupt()`, but that
function only finalized the local streaming message and never emitted
`chat:interrupt`, so the visible UI stopped while backend generation/audio could
continue.

### Memory organize refresh no-op

`useChat.organizeMemory()` emitted `memory:organize` and then listened for
`memory:organize_result`, but its intended wiki refresh sent a bare
`memory:list_pages` event without the callback required by the frontend memory
store. The backend returned pages through the Socket.IO ack path, so the
post-organize refresh never updated `wikiPages`.

### Meme review event catalog without backend routes

`config/socket-events.json` and the frontend exposed `meme:add`, `meme:list`,
`meme:review`, `meme:dataset`, and `meme:collect`, but `register_routes()` did
not bind any of those events to backend handlers. The Meme Review UI could emit
catalog-valid events, but no server-side business boundary received them.

## Fixed In This Patch

| Fix | Files |
| --- | --- |
| Added `event_name(module, action)` backend accessor that fails fast when an event is absent from the catalog. | `src/animetta/orchestration/socket_events.py` |
| Replaced inbound route-registration fallback strings with `event_name(...)`. | `src/animetta/orchestration/server/routes.py` |
| Added `minecraft.command` to the shared JSON catalog and frontend constants. | `config/socket-events.json`, `frontend/src/constants/socket-events.ts` |
| Added focused tests for configured lookup, missing lookup, and the Minecraft command catalog entry. | `tests/orchestration/test_socket_events.py` |
| Expanded event validation to cover frontend socket literals, Python socket listeners, and helper/test scripts, then updated stale script and integration-test event names to the catalog-backed `chat:*` / `system:error` names. | `scripts/validate-events.py`, `scripts/bench.py`, `scripts/test_mc_e2e.py`, `tests/smoke/conversation_e2e.py`, `tests/smoke/test_validate_events.py`, `tests/integration/` |
| Delegated tracing bootstrap solely to `create_server()` and added an entrypoint boundary test. | `src/animetta/core/socketio_server.py`, `tests/core/test_socketio_server.py` |
| Moved stale `animetta.core.config` references to `animetta.config` without reintroducing the deleted namespace. | `src/animetta/__init__.py`, config/service tests |
| Updated startup docs and stale CLI prompt text to the current entrypoint. | `src/animetta/core/AGENTS.md`, `src/animetta/utils/auto_config.py` |
| Fixed MCP tool discovery to use the current SDK `ListToolsResult.tools` field and added a regression test. | `src/animetta/tools/mcp_bridge.py`, `tests/tools/test_mcp_bridge.py` |
| Fixed DuckDuckGo fallback import to the current LangChain Community tools namespace and added a no-network fallback test. | `src/animetta/tools/base.py`, `tests/tools/test_base.py` |
| Moved stale tools tests from `animetta.core.tools` / `*.core.tools` wrapper expectations to the current `animetta.tools` and flat `ToolManager` shape. | `tests/tools/`, `tests/orchestration/graph/test_tool_manager.py` |
| Fixed LangChain adapter model-name detection to prefer current provider `.config` metadata while retaining legacy `.core.config` fallback. | `src/animetta/services/llm/langchain_adapter.py`, `tests/services/test_langchain_adapter.py` |
| Made `health_check.py` skip stale Python interpreters that cannot import required health-gate dependencies. | `scripts/health_check.py`, `tests/smoke/test_health_check.py` |
| Made the RVC VC provider lazy so `VCFactory` and `MockVC` do not require optional RVC/audio dependencies at package import time. | `src/animetta/services/vc/__init__.py`, `src/animetta/services/vc/factory.py`, `tests/services/vc/test_vc_factory.py` |
| Updated stale tests from removed `.core.config` wrapper assertions to the current direct `.config` attributes and current handler config propagation. | `tests/core/test_service_context.py`, `tests/orchestration/server/test_websocket.py`, `tests/avatar/test_position_strategy.py`, `tests/services/test_live2d_viseme_sync.py`, `tests/orchestration/server/test_routes.py` |
| Fixed split server handlers that still relied on missing imports or removed `.core.config` wrappers in Bilibili, translation, and persona event paths. | `src/animetta/orchestration/server/handlers/bilibili_handlers.py`, `src/animetta/orchestration/server/handlers/config_handlers.py`, `src/animetta/orchestration/server/handlers/persona_handlers.py`, `tests/orchestration/server/test_routes.py` |
| Routed Bilibili auto-start through the active `AppConfig.bilibili` object instead of re-reading YAML from `WebSocketServer`. | `src/animetta/orchestration/server/websocket.py`, `tests/orchestration/server/test_websocket.py` |
| Fixed `config:get` to list personas from the project config directory and to load Live2D settings through the current `get_live2d_config()` entrypoint. | `src/animetta/orchestration/server/handlers/config_handlers.py`, `tests/orchestration/server/test_routes.py` |
| Fixed enhanced persona prompt loading to use the project `config/personas` directory by default. | `src/animetta/config/persona/enhanced.py`, `tests/config/test_persona.py` |
| Centralized the Socket.IO entrypoint project root path so user settings, `.env`, logs, and frontend serving resolve from the same project root. | `src/animetta/core/socketio_server.py`, `tests/core/test_socketio_server.py` |
| Closed partially initialized pooled LLM/TTS/ASR engines when `ServicePool` initialization fails. | `src/animetta/core/service_pool.py`, `tests/core/test_service_pool.py` |
| Moved Memory/Wiki socket business logic out of the route facade and routed it through the shared handler config/context boundary. | `src/animetta/orchestration/server/routes.py`, `src/animetta/orchestration/server/handlers/base_handler.py`, `src/animetta/orchestration/server/handlers/memory_handlers.py`, `tests/orchestration/server/test_routes.py` |
| Routed `config:get` through the shared handler `get_active_config()` fallback instead of a second direct `AppConfig.load()` call. | `src/animetta/orchestration/server/handlers/config_handlers.py`, `tests/orchestration/server/test_routes.py` |
| Centralized persona catalog path resolution and available-persona listing behind config-level helpers used by persona loading and server handlers. | `src/animetta/config/persona/base.py`, `src/animetta/config/persona/enhanced.py`, `src/animetta/orchestration/server/handlers/config_handlers.py`, `src/animetta/orchestration/server/handlers/persona_handlers.py`, `tests/config/test_persona.py` |
| Re-aligned inspection checks with the current probe filter, Socket.IO event catalog, runtime log filename, and idle-safe StatsStore reachability semantics. | `src/animetta/inspection/checks/pipeline.py`, `src/animetta/inspection/checks/consistency.py`, `tests/inspection/test_pipeline.py`, `tests/inspection/test_consistency.py` |
| Routed `persona:list` MBTI extraction through the active `AppConfig.get_persona()` cache instead of reloading the current persona by name. | `src/animetta/orchestration/server/handlers/persona_handlers.py`, `tests/orchestration/server/test_routes.py` |
| Sanitized persona-handler config diagnostics, including `persona:list`, so they report propagation state without logging full config object representations. | `src/animetta/orchestration/server/handlers/persona_handlers.py`, `tests/orchestration/server/test_routes.py` |
| Made `/health` return HTTP 503 for degraded component checks and HTTP 500 when the health-check runner itself crashes instead of returning 200 with an unhealthy body. | `src/animetta/orchestration/server/stats_api.py`, `tests/orchestration/server/test_stats_api.py` |
| Replaced full config dumps and API-key prefix logging during config env expansion with provider type and key-length diagnostics. | `src/animetta/config/app.py`, `tests/config/test_app_config.py` |
| Replaced full tool-config logging during orchestrator creation and `tools.yaml` loading with enabled-state and key-name diagnostics. | `src/animetta/orchestration/server/session.py`, `tests/orchestration/server/test_session.py` |
| Covered `/api/stats/inspection/latest` and updated the API reference to the persisted StatsStore report shape. | `tests/orchestration/server/test_stats_api.py`, `docs/reference/backend-api.md` |
| Added `/metrics` to the lightweight ASGI route smoke probe so observability routing is covered by the health gate. | `scripts/route_smoke.py`, `tests/smoke/test_route_smoke.py` |
| Added stats API paths to lightweight ASGI route smoke and tightened route registration assertions for dynamic trace/detail routes. | `scripts/route_smoke.py`, `tests/smoke/test_route_smoke.py`, `tests/orchestration/server/test_stats_api.py` |
| Added method-aware route smoke coverage for `POST /api/config/reload` and asserted that successful HTTP reload applies the reloaded config to existing contexts. | `scripts/route_smoke.py`, `tests/smoke/test_route_smoke.py`, `tests/orchestration/server/test_config_reload_api.py` |
| Removed the unused stale frontend `SystemModelStatusPayload` shape and aligned the event catalog payload with the runtime `{service, name, status, error?}` contract. | `frontend/src/constants/socket-events.ts`, `frontend/src/types/model-loading.ts`, `config/socket-events.json`, `tests/orchestration/test_socket_events.py` |
| Aligned `translation:configure` with partial updates and wired the subtitle enable toggle to the shared backend translation state. | `config/socket-events.json`, `src/animetta/orchestration/server/handlers/config_handlers.py`, `frontend/src/components/settings/SettingsPanel.vue`, `tests/orchestration/server/test_routes.py`, `tests/orchestration/test_socket_events.py` |
| Added `current_persona` to `persona:list`, tracked it in the frontend personality store, and rendered the drawer persona card from the active persona instead of the first catalog entry. | `src/animetta/orchestration/server/handlers/persona_handlers.py`, `frontend/src/stores/personality.ts`, `frontend/src/components/layout/PersonaCard.vue`, `frontend/src/components/personality/PersonalityPanel.vue` |
| Routed Minecraft viewer error events into frontend state and surfaced them in the settings panel with retry enabled. | `frontend/src/stores/minecraft.ts`, `frontend/src/components/settings/SettingsPanel.vue`, `frontend/src/stores/__tests__/minecraft.test.ts` |
| Reconnected the frontend interrupt button to the backend `chat:interrupt` handler while keeping local response finalization. | `frontend/src/composables/useChat.ts`, `frontend/src/composables/__tests__/useChat.test.ts` |
| Routed memory organize completion through the frontend memory store refresh instead of a no-op `memory:list_pages` emit. | `frontend/src/composables/useChat.ts`, `frontend/src/composables/__tests__/useChat.test.ts` |
| Added backend meme review handlers and route registration for the existing `meme:*` catalog events. | `src/animetta/orchestration/server/handlers/meme_handlers.py`, `src/animetta/orchestration/server/routes.py`, `tests/orchestration/server/test_routes.py` |

Behavior preserved:

- Existing Socket.IO event names are unchanged.
- `python -m animetta.core.socketio_server` remains the runtime entrypoint.
- `minecraft:command` remains registered, now through the shared catalog.
- Helper scripts and integration tests now exercise the same catalog-backed
  event names as production clients.
- Config models remain exported from package root lazy attributes, now through
  the current `animetta.config` package.
- MCP servers that return tools through the current SDK shape now populate
  LangChain tools instead of being silently treated as empty.
- `web_search` still prefers Tavily when configured and now reaches its
  DuckDuckGo fallback when Tavily is absent.
- LangChain chat model construction preserves model metadata for current LLM
  providers and still accepts legacy wrappers exposing `core.config`.
- Health checks no longer fail solely because a stale repository `.venv` exists.
- Importing the VC package no longer loads the heavy RVC provider unless RVC is
  explicitly requested.
- Bilibili auto-start still receives the same `enabled`, `room_id`, and
  `sessdata` fields, now from the parsed runtime config object.
- Successful service-pool initialization still keeps LLM/TTS/ASR alive for
  sharing; only failed partial initialization now closes those engines.
- `memory:organize` and `memory:list_pages` keep the same public event behavior,
  now delegated from `RouteHandlers` to `MemoryHandlers`.
- `config:get` keeps the same sanitized response shape while using the shared
  server-handler config fallback.
- Persona loading and persona listing still read the same project
  `config/personas/*.yaml` catalog; `persona:list` keeps its `default` fallback.
- `persona:list` still returns current MBTI data when available, now from the
  active config persona cache.
- Persona handler config propagation and `persona:list` behavior are unchanged;
  diagnostics now log booleans/names instead of full config object
  representations.
- Config environment expansion behavior is unchanged; debug diagnostics now log
  provider type and secret length only, never secret values or prefixes.
- Tool configuration behavior is unchanged; diagnostics now log enabled state
  and key names only, never raw tool or MCP credential values.
- `/health` still returns HTTP 200 with `status: "ok"` when all component
  probes pass; degraded checks now return 503 and infrastructure-level
  health-check crashes return 500.
- `/api/stats/inspection/latest` keeps returning the latest persisted
  inspection report, now with explicit route coverage and matching reference
  documentation.
- `/metrics` behavior is unchanged; it is now part of the lightweight route
  smoke gate when `prometheus-client` is installed.
- Stats API behavior is unchanged; overview, nodes, traces, and missing trace
  detail/tree routes are now part of the lightweight route smoke gate.
- Runtime config reload behavior is unchanged; the no-active-config route
  response is now part of the lightweight route smoke gate, and successful HTTP
  reload is asserted to update existing session contexts.
- `system:model_status` behavior is unchanged; the frontend and event catalog
  now keep only the active `{service, name, status, error?}` payload contract
  used by the store and `ModelLoadingManager`.
- `translation:configure` keeps the same event name and status response; callers
  can now update either `enabled`, `target_language`, or both without sending
  stale required fields.
- Persona switching behavior is unchanged; the frontend now receives and
  displays the active persona explicitly instead of inferring it from the
  catalog order.
- Minecraft start/stop/spectate event names are unchanged; viewer spectate
  failures now update visible frontend state instead of leaving stale state.
- Chat interrupt UI behavior still finalizes the local message immediately,
  and now also notifies the backend interrupt handler.
- Memory organize still emits the same backend event and clears the organizing
  state on completion; the wiki list now refreshes through the memory store ack
  path.
- Meme review event names are unchanged; existing frontend emit/once and ack
  callers now reach a backend handler backed by the existing meme services.
- Inspection probes still avoid dispatching internal pings to the LLM; the
  conversation check now verifies connection/probe containment instead of
  expecting output events from a filtered probe.
- Data consistency still checks StatsStore, Chroma, and log freshness; recent
  user traces are now diagnostic only, so an otherwise healthy idle service does
  not fail inspection.

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
there are still category-specific factory helpers and the three classified
config load timings listed above. Consolidating this should wait until the
service-container boundary is designed explicitly.

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
4. Design whether `BaseSocketHandler.get_active_config()` should remain the
   request-time fallback or be replaced by an explicit runtime config provider.
5. Update stale architecture docs after runtime boundaries are settled.
