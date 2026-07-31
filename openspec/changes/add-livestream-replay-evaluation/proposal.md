## Why

Animetta can consume Bilibili danmaku, but it cannot preserve a privacy-safe livestream event stream or replay realistic low-, medium-, and high-heat sessions. A reproducible capture and Gateway-level evaluation path is needed to test both long-running stability and Aura's interaction quality before public broadcasts.

## What Changes

- Add a normalized livestream event model covering replyable messages, engagement signals, connection state, and unknown command accounting while preserving the existing `DanmakuMessage` contract.
- Add anonymous public-room capture that sanitizes events before persistence and writes a checksummed JSONL dataset plus manifest.
- Add a deterministic replay Gateway with injectable timing, speed profiles, burst windows, lifecycle cleanup, and event metrics.
- Add a CLI for capture, validation, replay, and reporting, including full conversation records and a seeded manual-scoring worksheet.
- Add low-, medium-, and high-heat workload definitions, automated stability gates, and transport/full-stack evaluation modes.
- Pin livestream-evaluation-only dependencies without changing the default runtime installation.

## Capabilities

### New Capabilities
- `livestream-replay-evaluation`: Defines privacy-safe Bilibili event capture, dataset validation, deterministic Gateway replay, workload tiers, evaluation metrics, reports, and manual scoring artifacts.

### Modified Capabilities
- `bilibili-shared-models`: Extends the shared Bilibili model contract with normalized livestream events while keeping `DanmakuMessage` backward-compatible.

## Impact

- Affects `src/animetta/services/bilibili/`, the Bilibili session/Gateway boundary, and their focused tests.
- Adds a standalone `evaluations/livestream/` CLI and generated data/evidence conventions under `data/livestream_eval/` and `artifacts/livestream-eval/`.
- Adds an optional, locked `bilibili-api-python` capture dependency and an async WebSocket client.
- Does not add a frontend control surface or change the existing public Socket.IO danmaku payload.
