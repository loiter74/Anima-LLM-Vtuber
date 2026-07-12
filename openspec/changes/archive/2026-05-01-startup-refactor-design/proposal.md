# Startup Script Refactoring Design

**Date:** 2026-05-01
**Status:** Design Approved
**Goal:** Split monolithic `scripts/start.py` (642 lines) into a modular `scripts/start/` package.

---

## Problem

`scripts/start.py` has grown to 642 lines with multiple concerns tangled:
- ANSI color helpers
- Process management (port finding, killing)
- 5 service startup methods (backend, Vite, web config, VibeVoice TTS, Next.js)
- Inline HTTP server as `python -c "..."` string
- Auto-open browser logic
- Dead code (Next.js references, unused `start_frontend_dev`)

## Solution

Split into `scripts/start/` package with clear module boundaries.

```
scripts/
├── start.py                  # Entry point (~100 lines: CLI + orchestration only)
└── start/
    ├── __init__.py            # Unified exports
    ├── colors.py              # ANSI color helpers + info/success/warn/error
    ├── process.py             # ProcessManager (port finding, killing)
    ├── services.py            # Service startup functions
    ├── web_config_server.py   # Standalone HTTP server for config page
    └── browser.py             # Auto-open browser logic
```

## Module Details

### `colors.py`
Move existing `Colors` class and 4 helper functions unchanged.

### `process.py`
Move `ProcessManager` class unchanged. Clean up: remove `start_frontend_dev` (Next.js dead code).

### `services.py`
Extract each startup method into standalone functions:
- `start_backend(project_root)` — returns `(name, process, port)`
- `start_vite(project_root)` — returns `(name, process, port_or_none)`
- `start_web_config(project_root, port)` — returns `(name, process, port)`
- `start_vibe_voice(project_root)` — returns `(name, process, port)` or `None`

### `web_config_server.py`
Extract the inline HTTP server code from the `python -c "..."` string into a proper standalone file. Same behavior: serves `templates/config.html` from `frontend/web/` with CORS headers.

### `browser.py`
Extract `_auto_open_browser()`. Takes list of `(url, delay)` pairs instead of duplicating URL logic.

### `start.py` (entry point)
Only:
1. Parse CLI args
2. Call service functions in order
3. Print status URLs
4. Auto-open browser
5. Wait for processes

## Behavioral Changes

- **No change** in CLI arguments, ports, or service startup order
- **No change** in process management or signal handling
- **Fix**: `--mode web` help text corrected from "Next.js" to "Vue 3 + Vite"
- **Fix**: `start_frontend_dev()` (dead Next.js code) removed
- **Improvement**: Web config server debuggable as a real file instead of inline string

## Non-Goals

- No new features or services
- No configuration file for startup (YAGNI)
- No changes to `stop.py` or other scripts
