## Why

The local livestream review flow is implemented across browser fixtures, URL parsing, Playwright metadata, evidence storage, and CLI orchestration with duplicated scene definitions and coupled lifecycle concerns. It needs one typed scene catalog and reusable review infrastructure so future standalone pages can add deterministic review plugins without copying the livestream runner.

## What Changes

- Add a reusable TypeScript review definition, timeline, lifecycle, evidence, and orchestration layer.
- Move livestream fixtures and expectations into one typed plugin catalog while preserving the frozen eight-scene order and copy.
- Replace the MJS runner with a TypeScript CLI that defaults to automatic Playwright plus OBS WebSocket evidence.
- Keep an optional `--interactive` human gate and an explicit `--no-obs` browser-only profile.
- Introduce append-only v2 evidence and validated automatic stable-round counting without rewriting v1 history.
- Automate OBS Browser Source setup, capture, synchronization checks, and restoration without streaming or recording.

## Capabilities

### New Capabilities

- `extensible-local-review-pipeline`: Static review plugin registration, automated scene orchestration, infrastructure adapters, and v2 evidence.

### Modified Capabilities

- `local-livestream-review`: Use the shared pipeline, default to automatic verdicts, and automate OBS evidence while preserving optional interactive review.
- `live-stream-page`: Use the single typed scene catalog and an explicitly disposable page session.

## Impact

- Frontend review contracts under `frontend/src/review/` and livestream plugin code under `frontend/src/live/review/`.
- Node review adapters and CLI under `frontend/scripts/review/`.
- Frontend package scripts, TypeScript/Vitest configuration, and impact-aware quality catalog.
- New v2 evidence under `artifacts/live-review/`; historical v1 evidence remains untouched.
- No backend event contract, Bilibili, AI, TTS, streaming, or recording changes.
