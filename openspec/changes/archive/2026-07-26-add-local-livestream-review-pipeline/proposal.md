## Why

Animetta has an OBS-ready standalone livestream page and a minimal demo mode, but it lacks a deterministic, private workflow for a human to review technical correctness and visual quality scene by scene. A local Playwright-driven review loop is needed so the operator can approve, adjust, or redo each scene with fresh evidence before the workflow is frozen into a repeatable pipeline.

## What Changes

- Add a local-only review mode for `live.html` that never connects to Bilibili, AI, TTS, or other external services.
- Add deterministic review scenes covering empty state, baseline danmaku, text boundaries, traffic pressure, gifts/super chats, panel collapse, and connection recovery.
- Add an interactive headed Playwright command, `pnpm live:review`, that opens a fresh 1080 × 1920 page for each scene, captures trace/screenshot/console/network evidence, and pauses for `pass`, `adjust`, or `redo`.
- Persist per-attempt evidence and a run summary so two unchanged end-to-end review rounds can be compared before the process is considered frozen.
- Preserve the production Socket.IO path and the existing `demo=1` entry point.

## Capabilities

### New Capabilities

- `local-livestream-review`: Deterministic local review scenes, human approval gates, Playwright browser operation, and per-attempt evidence capture.

### Modified Capabilities

- `live-stream-page`: Add an explicit local review mode and visual treatment for gift and super-chat fixture messages without changing the production event contract.

## Impact

- Frontend standalone livestream controller, view, styles, and tests under `frontend/src/live/`.
- Frontend scripts and package command used to run headed Playwright reviews.
- Generated review evidence under `artifacts/live-review/`.
- No backend API, Socket.IO catalog, Bilibili credentials, AI provider, or TTS behavior changes.
