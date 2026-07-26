## Context

The existing review flow has four sources of scene truth, source-file-based workflow fingerprints, a human-only CLI, manual OBS screenshot attachment, and incomplete process/page cleanup. Existing human-approved visual layout and playful fixtures are frozen behavior.

## Goals / Non-Goals

**Goals:**

- Make scene data, order, readiness, and observations derive from one typed catalog.
- Reuse a small static-plugin review core across future standalone pages.
- Run unattended by default with fresh Playwright and OBS evidence.
- Preserve an optional interactive visual gate without letting it override failed technical assertions.
- Make lifecycle ownership and v2 evidence deterministic and testable.

**Non-Goals:**

- Pixel-baseline aesthetic approval.
- Dynamic filesystem plugins.
- Real Bilibili, AI, TTS, streaming, or recording.
- Rewriting or repairing historical v1 evidence.

## Decisions

### 1. Pure contracts plus static feature plugins

`frontend/src/review/` owns browser-safe contracts, a discriminated timeline player, catalog validation, and a disposable stack. A static registry selects a plugin by feature ID. The livestream plugin owns its actions, fixtures, scene expectations, URL builder, and Playwright probe rules.

### 2. One declarative livestream catalog

Scene IDs are inferred from an `as const` scene tuple. Reusable builders add the common connection and live-status prefix. URL validation, CLI order, readiness text, fingerprint input, and browser runtime all derive from the same catalog. Frozen `text-boundaries`, `sparse`, and playful employee copy remain exact.

### 3. Explicit page session lifecycle

The page creates the event source without auto-starting it, mounts the controller and all listeners, then starts the session once. A shared disposer stack tears down timers, socket handlers, DOM handlers, resize listeners, and Pixi resources on unload or test cleanup.

### 4. Adapter-driven automatic orchestration

The generic runner depends on `ServerLease`, `BrowserDriver`, `PreviewDriver`, `DecisionPolicy`, and `EvidenceStore`. Automatic mode continues independent scenes after assertion failures and returns a non-zero result; infrastructure failures stop the run. Interactive mode runs technical gates first, then accepts `pass`, `adjust`, or `redo`.

### 5. OBS WebSocket is the default preview adapter

The OBS adapter connects to `ws://127.0.0.1:4455`, reads its password only from `OBS_WEBSOCKET_PASSWORD`, refuses active streaming/recording, creates or reuses a dedicated scene/source, refreshes the scene URL, captures `GetSourceScreenshot`, and restores the previous scene. A stable danmaku/status crop is compared with the Chrome crop using a tolerant cross-surface comparison; Live2D is excluded.

### 6. Evidence v2 is append-only and self-validating

Each run immediately writes `run.json` with `schema_version: 2` and lifecycle status. Attempts separate automatic `outcome` from optional human review. Artifact metadata includes relative path, SHA-256, byte size, dimensions, and capture time. Atomic writes prevent partial JSON. Stable rounds are recomputed only from consecutive automatic full-profile v2 summaries whose scene order, semantic fingerprint, and artifact metadata validate.

## Risks / Trade-offs

- **OBS credentials or WebSocket unavailable** → fail the full profile with an actionable error; require explicit `--no-obs` for browser-only diagnostics.
- **Cross-surface antialiasing differs** → compare only a stable crop with a manifest-owned tolerance, not the animated Live2D region.
- **Existing Vite server is user-owned** → `ServerLease` never terminates a server it did not start.
- **Large refactor hides behavior drift** → migrate by failing tests first and retain a thin compatibility export until all callers move.

## Migration Plan

1. Add shared contracts and the livestream catalog behind compatibility exports.
2. Move page runtime to explicit start/dispose and remove unreachable collapse behavior.
3. Add v2 evidence, server ownership, automatic policy, and OBS adapter with focused tests.
4. Switch package commands to the TypeScript registry CLI and remove superseded MJS files after parity.
5. Run fresh Playwright, OBS, impact, build, and Docker verification; reset stable rounds and execute two automatic full-profile runs.
