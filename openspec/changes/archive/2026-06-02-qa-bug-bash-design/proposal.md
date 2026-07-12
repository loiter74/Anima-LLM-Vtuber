# QA Bug Bash — Design Document

**Date:** 2026-06-02
**Source:** `/qa` session on `main` branch, QA report: `.gstack/qa-reports/qa-report-localhost-3000-2026-06-02.md`
**Health Score:** 81.75/100 (baseline)
**Target Score:** 95+/100

## Overview

Fix 11 issues discovered during comprehensive QA testing of the Animetta frontend (Vue 3 + Vite) and backend (FastAPI + LangGraph + Socket.IO). Split into 3 openspec changes for independent execution and rollback.

## Architecture

```
qa-bug-bash/
├── qa-frontend-fixes       # 5 frontend fixes + test bootstrap
├── qa-backend-crash-fixes  # 3 backend crash fixes
└── qa-observability-polish # 2 observability fixes
```

**Execution order:** Backend crash fixes → Frontend fixes → Observability polish

---

## Change 1: `qa-backend-crash-fixes`

### Fix 1: Inspection Scheduler Import Error

**Root cause:** `src/animetta/inspection/scheduler.py:78` calls `run_full_inspection()` without importing it. Same for `store_report()` (line 79) and `send_alert()` (line 82).

**Fix:**
```python
# scheduler.py — add imports at top
from .inspector import run_full_inspection
from .reporter import store_report, send_alert
```

**Verification:** Restart server, check logs for `[inspection:scheduler] Inspection loop crashed` absence.

### Fix 2: FunASR Config Attribute Error

**Root cause:** `src/animetta/services/asr/factory.py:50` — `FunASRConfig` is a Pydantic V2 model accessed with `.get()` (dict-style), causing `'FunASRConfig' object has no attribute 'get'`.

**Fix:** Check factory's config access pattern. If `config.get("key")` → change to `config.key` or `getattr(config, "key", default)`. Pydantic V2 models use attribute access, not dict methods.

**Verification:** Set ASR profile to `funasr`, restart, check logs for `Falling back to Mock` absence.

### Fix 3: StatsStore Not Available

**Root cause:** `[StatsExporter] StatsStore not available` — the OpenTelemetry StatsExporter tries to write before StatsStore is initialized during server startup.

**Fix:** Add lazy initialization or `None` guard in the exporter. Option: make the exporter buffer writes until StatsStore is ready, or defer exporter registration to after StatsStore init.

**Verification:** Restart server, check for `StatsStore not available` absence.

---

## Change 2: `qa-frontend-fixes`

### Fix 4: Dashboard Overlay Blocks TitleBar

**Root cause:** After opening a sidebar panel (e.g., Settings), a `fixed inset-0 z-50` modal backdrop remains visible and intercepts clicks on TitleBar buttons (Dashboard, 梗筛选, 音乐制作).

**Evidence:** Playwright: `<div class="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"> subtree intercepts pointer events`

**Fix:** Option A (preferred): Add `pointer-events: none` to the backdrop overlay when the panel is closed but the overlay hasn't been removed yet. Or ensure overlay is removed in the same tick as panel close.
Option B: Raise TitleBar z-index above the overlay (fragile, may break other modals).

**Files:** `frontend/src/components/layout/` (TitleBar, AppLayout, InteractivePanel)

**Verification:** Open Settings panel → close it → click Dashboard in TitleBar. Button must respond.

### Fix 5: ARIA Labels on All Buttons

**Root cause:** 16 buttons lack `aria-label` or `aria-labelledby`. Icon-only buttons (reset, navigation) are completely invisible to screen readers.

**Fix:** Add `aria-label` to every button that has no visible text or has icon-only content. Examples:
- Reset buttons: `aria-label="复位 Live2D 位置"`
- Navigation: `aria-label="切换到聊天页面"`
- Sidebar toggle: `aria-label="展开侧边栏"`

**Files:** All `.vue` components with `<button>` elements, especially in `components/layout/`, `components/live2d/`, `components/shared/`.

### Fix 6: Semantic Heading Structure

**Root cause:** 0 H1 tags. No `<h1>` anywhere. Screen readers cannot navigate the document structure.

**Fix:** Add one `<h1>` per route-level view (hidden visually with `sr-only` if needed for design reasons). Add `<h2>` for major sections within views.

**Files:** `frontend/src/views/*.vue`

### Fix 7: Frontend Test Bootstrap

**Root cause:** `AGENTS.md` confirms: "No frontend tests exist — test framework not yet installed."

**Fix:**
1. Install vitest + @vue/test-utils + jsdom
2. Write `vitest.config.ts` (already exists: `frontend/vitest.config.ts`)
3. Write 3-5 smoke tests:
   - Router: all 4 routes resolve to components
   - App: mounts without errors
   - Chat store: initial state is correct
   - InputBar: renders and accepts input
4. Add `pnpm test` script to `package.json`

### Fix 8: WebGL GPU Stall (Live2D)

**Root cause:** 4x `GPU stall due to ReadPixels` warnings. Live2D rendering uses synchronous `gl.readPixels()` which blocks the GPU pipeline.

**Fix:** Option A: Use asynchronous PBO (Pixel Buffer Object) for readback instead of sync `readPixels`.
Option B: If live2d-display library controls this, reduce render frequency or accept as hardware limitation on headless GPU.

**Files:** `frontend/src/components/live2d/useLive2D.ts`

---

## Change 3: `qa-observability-polish`

### Fix 9: Duplicate TracerProvider Override

**Root cause:** `Overriding of current TracerProvider is not allowed` ×2. `init_tracing()` is called twice during startup (once in `socketio_server.py` and once in the imported module chain).

**Fix:** Add a module-level guard flag:
```python
_TRACER_INITIALIZED = False

def init_tracing(...):
    global _TRACER_INITIALIZED
    if _TRACER_INITIALIZED:
        return
    # ... existing init logic ...
    _TRACER_INITIALIZED = True
```

**Verification:** Restart, check logs for `Overriding` absence.

### Fix 10: flash-attn Installation Guidance

**Root cause:** TTS service warns `flash-attn is not installed. Will only run the manual PyTorch version.` No documentation tells users how to install.

**Fix:** Add install instruction to README or TTS service docs. Add optional dependency comment in `requirements.txt`.

---

## Implementation Plan

| Change | Estimated Time | Risk | Priority |
|--------|---------------|------|----------|
| `qa-backend-crash-fixes` | ~30 min | Low | P0 |
| `qa-frontend-fixes` | ~2 hours | Medium | P1 |
| `qa-observability-polish` | ~15 min | Low | P2 |

**Regression test strategy:** Each fix verified by restarting the server + running the Playwright QA script. Backend fixes verified via log output. Frontend fixes verified via browser inspection + accessibility audit.

## Non-Goals

- Not fixing the `40.5% error rate` shown in Dashboard (requires deeper StatsStore investigation)
- Not refactoring the FunASR provider code (just fix the config access pattern)
- Not rewriting the inspection scheduler (just fix the missing imports)
- Not redesigning the Live2D rendering pipeline (just fix the sync read issue)
