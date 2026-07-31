## Context

The production Bilibili path currently converts `DANMU_MSG`, gifts, super chats, and entry notifications into `DanmakuMessage`. This loses engagement-event identity, makes entry events eligible for ordinary-message sampling, and provides no privacy-safe recording or deterministic replay. `LivestreamSession` already accepts a Gateway factory, which is the narrowest boundary that can exercise lifecycle, raw delivery, admission, and reply queues without connecting to Bilibili.

The evaluator must support 90–120 minute runs, preserve the existing Socket.IO message payload, avoid persisting public room identities, and keep live-capture dependencies out of the default runtime dependency set.

## Goals / Non-Goals

**Goals:**

- Normalize Bilibili messages, engagement signals, connection state, and unknown-command counts without breaking `DanmakuMessage` callers.
- Sanitize events before persistence and validate every replay dataset deterministically.
- Replay a dataset through the production Gateway/session boundary with real-time, accelerated, and burst timing profiles.
- Produce machine-readable stability evidence, complete sanitized conversation logs, and a deterministic manual-scoring worksheet.
- Define repeatable low-, medium-, and high-heat workload contracts.

**Non-Goals:**

- Discover or scrape lists of public rooms.
- Persist raw protocol payloads, room IDs, UIDs, nicknames, credentials, or absolute capture timestamps.
- Use captured data for model training.
- Add a frontend capture/replay control panel.
- Make engagement-only events generate AI replies.

## Decisions

### 1. Normalize events before the Gateway/session boundary

Add a frozen `LivestreamEvent` dataclass and `LivestreamEventType` enum. `DanmakuGateway` gains an event callback while retaining the legacy message callback as a compatibility adapter. `LivestreamSession` handles all events, updates event metrics, and converts only danmaku, gift, and super-chat events into `DanmakuMessage` for the existing raw-message and reply paths.

Handler-level injection was rejected because it bypasses Gateway lifecycle and transport scheduling. Offline-only evaluation was rejected because it cannot validate session backpressure or cleanup.

### 2. Persist a strict, sanitized JSONL contract

Each dataset contains `manifest.json` and `events.jsonl`. The event file stores sequence, relative offset, type, dataset-local actor alias, sanitized text, and a per-type payload whitelist. The writer maps identities in memory, sanitizes text before serialization, and never creates a raw spool. The manifest stores schema/tool versions, heat tier, duration, counts, rate percentiles, sanitizer version, and the SHA-256 digest of the exact event file.

Unknown commands retain only a sanitized command name and count. This preserves observability without retaining an unreviewed payload.

### 3. Use a threaded replay Gateway with injectable timing

`ReplayDanmakuGateway` matches the production Gateway lifecycle: `start()` returns after starting one daemon thread, `stop()` is idempotent and joins it within five seconds, and callbacks are never emitted after stop. A scheduler computes target monotonic times from dataset offsets, base speed, and ordered burst windows. Unit tests inject a fake monotonic clock and wait function.

### 4. Keep evaluation orchestration standalone

Place the CLI and reports under `evaluations/livestream/`, separate from runtime imports. The CLI exposes `capture`, `validate`, `replay`, and `report`. Capture imports `bilibili-api-python` lazily and returns an actionable dependency error when the optional group is absent.

### 5. Separate event metrics from reply metrics

Keep `ReplyMetrics.received` and `displayed` scoped to replyable messages. Add `LivestreamEventMetrics` for per-type input/dispatched counts, scheduling lag samples, callback failures, and peak callback tasks. Reports join both metric sets without changing existing metrics consumers.

### 6. Use fixed workload and annotation contracts

Heat is based on replyable-message rate in 60-second windows: low 1–10/minute, medium 11–60/minute, high 61–300/minute. A source qualifies when at least 80% of observed windows remain in range. High heat adds the approved 2×/3× burst schedule. Manual scoring uses a fixed seed and selects five gift/SC, fifteen question, and ten ordinary replies per canonical run, redistributing shortages deterministically.

## Risks / Trade-offs

- [Bilibili command schemas change] → Pin the optional client, maintain decoded command fixtures, count unknown commands, and require fixture tests before dependency upgrades.
- [Sanitization misses identifying text] → Reject known identifier patterns during validation, quarantine risky events, and keep room/actor source data out of persisted files entirely.
- [A public room changes heat during capture] → Validate 60-second windows and reject datasets below the 80% qualification threshold.
- [Accelerated replay distorts content timing] → Use 10× only for transport tests; full-stack quality runs remain 1× except the explicit high-heat burst windows.
- [Resource gates vary by hardware] → Hard-gate only event integrity, lifecycle, queue, failures, and RSS growth; report CPU/GPU without fixed limits.
- [Legacy consumers expect message callbacks] → Retain the callback and `DanmakuMessage` conversion adapter and cover it with regression tests.

## Migration Plan

1. Introduce event models and compatibility conversion with no behavior change for existing replyable messages.
2. Update the production service and session to emit/consume events while keeping the legacy callback.
3. Add the standalone dataset, replay, and reporting modules plus optional dependencies.
4. Validate focused tests and the impact-aware quality catalog.
5. Capture nine operator-selected datasets outside Git, validate them, then establish three canonical baselines.
6. Roll back by selecting the existing production Gateway and leaving evaluator modules unused; no stored runtime data migration is required.

## Open Questions

None. Target room IDs are operator inputs in an ignored local file and are not part of the implementation contract.
