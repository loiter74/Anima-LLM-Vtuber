# ANIMETTA CORE — PROCESS ENTRY + COMPATIBILITY FACADES

**Generated:** 2026-06-15
**Scope:** `src/animetta/core/` — the outer process entry and one-release compatibility imports.

> Parent: [../../../AGENTS.md](../../../AGENTS.md) · Sibling: [../AGENTS.md](../AGENTS.md) (backend package map).

## OVERVIEW

Owns the CLI/process bootstrap. Provider, session, model-loading, checkpoint and readiness
lifecycle implementations live in `animetta.runtime`; their old `core` paths are terminal
compatibility facades and must not be imported by new production code.

## STRUCTURE

| File | Role |
|------|------|
| `socketio_server.py` | Entry point. Parses `--redis-url`, resolves one immutable `EffectiveConfig`, constructs `WebSocketServer`, runs uvicorn ASGI factory. |
| `service_pool.py` | Compatibility re-export of `runtime.provider_pool`. |
| `service_context.py` | Compatibility re-export of `runtime.session_context`. |
| `model_loading_manager.py` | Compatibility re-export of `runtime.model_loading`. |
| `redis_checkpoint.py` | Compatibility re-export of `runtime.checkpoint`. |
| Other former runtime modules | Compatibility re-exports of their `runtime` or `services.dialogue` owners. |
| `__init__.py` | (Empty package marker.) |

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Change boot order | `socketio_server.py:get_asgi_app` | Single ASGI factory; order matters. |
| Add a shared engine | `../runtime/provider_pool.py` | One pool instance belongs to one `WebSocketServer`. |
| Per-session state | `../runtime/session_context.py` | VAD, Memory, emotion analyzer and audio are never pooled. |
| Model warmup hooks | `../runtime/model_loading.py` | Register loader → `await manager.get(name)` uniform API. |
| Multi-instance sessions | `../runtime/checkpoint.py` + `--redis-url` | Falls back to MemorySaver if Redis unreachable. |
| Frontend static serving | `socketio_server.py:_wrap_with_frontend_serving` | SPA middleware; pass-through for `/api/`, `/socket.io`, `/metrics`. |
| CLI args | `socketio_server.py:parse_server_args` | Only `--redis-url` exists. No `--mode`, no `--no-app`. |

## STARTUP SEQUENCE (`get_asgi_app`)

`_INIT_DONE` Event guards against double-init on uvicorn reload. Order:
1. Load `.env` (module top) → parse `--redis-url` → resolve `config/animetta.yaml` for `ANIMETTA_PROFILE` + `UserSettings` + log level.
2. Add file logger `logs/animetta.log` (daily rotation, 7-day retention, for Loki).
3. `create_server(config)` constructs a `WebSocketServer`; that application owns its
   provider pool, checkpoint runtime, shared memory runtime and route/session composition.
4. The server lifespan initializes and closes those application-owned dependencies.
5. Background `asyncio.ensure_future` tasks: `model_manager.warmup()`, `prewarm_services()`, `InspectionScheduler.start()` (24h interval).
6. `_INIT_DONE.set()` → wrap ASGI with FrontendServingMiddleware → return.

`run_server()` (CLI path) calls `init_config()` then `uvicorn.run(..., factory=True)` which re-enters `get_asgi_app` in a subprocess — that's why `_INIT_DONE` is a `threading.Event`.

## CONVENTIONS

- **Application-owned provider pool**: each `WebSocketServer` receives its own
  `runtime.ProviderPool`; the old class API only backs compatibility imports.
- **Background tasks tracked in `_INIT_TASKS`** so stale ones from a prior init can be cancelled.
- **Non-fatal init failures**: inspection scheduler and Redis log warning and continue; tracing is delegated to `orchestration.server.websocket.create_server()`.
- **Model loading is concurrent and awaitable**: `ModelSlot.wait(timeout=30)` raises the original error on failure.
- **Checkpoints expire at 86400s** (24h); key shape `checkpoint:{thread_id}` + `checkpoint_writes:{thread_id}`.

## ANTI-PATTERNS

- ❌ **NEVER** add new runtime behavior to a `core` compatibility facade; change its canonical owner in `runtime` or `services`.
- ❌ **NEVER** call `ctx.close()` on the provider pool's internal context — the pool owns the shared engines and closes them once.
- ❌ **NEVER** pool VAD / Memory / emotion_analyzer / audio_processor — they carry per-session state. Pool's `init` explicitly closes/discards these.
- ❌ **NEVER** reference `scripts/start.py` or `--mode`/`--no-app` flags — removed; only `python -m animetta.core.socketio_server` exists.
- ❌ **NEVER** rely on `asgi_app is None` for re-init detection — uvicorn reload breaks module globals; use `_INIT_DONE.is_set()`.
- ❌ **NEVER** block startup on Redis — 5s timeouts + MemorySaver fallback are by design.

## COMMANDS

```bash
# Entry (only valid way to boot backend)
PYTHONPATH=src python -m animetta.core.socketio_server

# With Redis-backed session sharing (multi-instance)
PYTHONPATH=src python -m animetta.core.socketio_server --redis-url redis://localhost:6379

# Inside container
docker compose exec animetta python -m animetta.core.socketio_server --redis-url $REDIS_URL
```

## NOTES

- `_server` / `asgi_app` are module globals populated lazily — `get_asgi_app()` is the single factory entry.
- Frontend SPA fallback requires `frontend/dist/index.html`; missing dist only warns, backend still serves.
- `prewarm_services()` creates a throwaway ServiceContext to trigger all imports before first user request (cold-start mitigation).
- `AsyncRedisSaver.alist` is minimal (yields at most one tuple) — sufficient for current graph usage.
- Connection timeouts (5s connect, 5s socket) prevent a down Redis from blocking boot.
