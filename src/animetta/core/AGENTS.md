# ANIMETTA CORE — ENTRY POINT + SERVICE CONTAINER

**Generated:** 2026-06-15
**Scope:** `src/animetta/core/` — the innermost layer that boots the process and wires shared engines.

> Parent: [../../../AGENTS.md](../../../AGENTS.md) · Sibling: [../AGENTS.md](../AGENTS.md) (backend package map).

## OVERVIEW

6 files, no subdirs. Owns: ASGI bootstrap, ServicePool (shared LLM/TTS/ASR), ServiceContext (per-session), ModelLoadingManager (GPU lifecycle), AsyncRedisSaver (LangGraph checkpoint). All cross-cutting startup wiring lives here — business logic does NOT.

## STRUCTURE

| File | Role |
|------|------|
| `socketio_server.py` | Entry point. Parses `--redis-url`, resolves one immutable `EffectiveConfig`, constructs `WebSocketServer`, runs uvicorn ASGI factory. |
| `service_pool.py` | Class-level singleton holding shared LLM/TTS/ASR engines. Stateless engines only — VAD/Memory/emotion are per-session. |
| `service_context.py` | Request-scoped container: ASR/TTS/LLM/VAD/Memory/emotion/audio per session. 460 lines. |
| `model_loading_manager.py` | `ModelLoadingManager` + `ModelSlot` — concurrent warmup, asyncio.Event-based waiting, Socket.IO status reporting. |
| `redis_checkpoint.py` | `AsyncRedisSaver(BaseCheckpointSaver)` — thread_id → Redis key, 86400s TTL, 5s socket timeouts, JSON serialization. |
| `__init__.py` | (Empty package marker.) |

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| Change boot order | `socketio_server.py:get_asgi_app` | Single ASGI factory; order matters. |
| Add a shared engine | `service_pool.py:init` | Extract from throwaway ServiceContext, stash as `_llm`/`_tts`/`_asr`. |
| Per-session state | `service_context.py` | VAD, Memory, emotion_analyzer — NEVER pooled. |
| Model warmup hooks | `model_loading_manager.py` | Register loader → `await manager.get(name)` uniform API. |
| Multi-instance sessions | `redis_checkpoint.py` + `--redis-url` | Falls back to MemorySaver if Redis unreachable. |
| Frontend static serving | `socketio_server.py:_wrap_with_frontend_serving` | SPA middleware; pass-through for `/api/`, `/socket.io`, `/metrics`. |
| CLI args | `socketio_server.py:parse_server_args` | Only `--redis-url` exists. No `--mode`, no `--no-app`. |

## STARTUP SEQUENCE (`get_asgi_app`)

`_INIT_DONE` Event guards against double-init on uvicorn reload. Order:
1. Load `.env` (module top) → parse `--redis-url` → resolve `config/animetta.yaml` for `ANIMETTA_PROFILE` + `UserSettings` + log level.
2. Add file logger `logs/animetta.log` (daily rotation, 7-day retention, for Loki).
3. `_setup_checkpointer()` → if `--redis-url`: `AsyncRedisSaver` + `set_external_checkpointer`; else MemorySaver default.
4. `create_server(config)` → initializes tracing/routes/lifecycle, then `_server.set_user_settings(...)`.
5. Background `asyncio.ensure_future` tasks: `model_manager.warmup()`, `prewarm_services()`, `InspectionScheduler.start()` (24h interval).
6. `_INIT_DONE.set()` → wrap ASGI with FrontendServingMiddleware → return.

`run_server()` (CLI path) calls `init_config()` then `uvicorn.run(..., factory=True)` which re-enters `get_asgi_app` in a subprocess — that's why `_INIT_DONE` is a `threading.Event`.

## CONVENTIONS

- **Class-level state for ServicePool**: `_llm`/`_tts`/`_asr`/`_ready`/`_ctx` are classvars; `init()` is idempotent.
- **Background tasks tracked in `_INIT_TASKS`** so stale ones from a prior init can be cancelled.
- **Non-fatal init failures**: inspection scheduler and Redis log warning and continue; tracing is delegated to `orchestration.server.websocket.create_server()`.
- **Model loading is concurrent and awaitable**: `ModelSlot.wait(timeout=30)` raises the original error on failure.
- **Checkpoints expire at 86400s** (24h); key shape `checkpoint:{thread_id}` + `checkpoint_writes:{thread_id}`.

## ANTI-PATTERNS

- ❌ **NEVER** call `ctx.close()` on the ServicePool's internal `_ctx` — destroys shared LLM/TTS/ASR engines. Pool intentionally keeps it alive.
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
