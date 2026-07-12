## Context

Animetta's conversation runtime now has two real graph topologies: the golden two-pass graph and the standard graph with memory recall, optional tools, humor processing, TTS, emotion, and output. Voice input adds VAD and ASR, while the application-owned SharedMemoryRuntime continues work after the visible turn through ingestion and indexing workers.

The current observation implementation predates those changes. LangGraph callbacks filter node names through a legacy allowlist, the orchestrator creates synthetic `input/llm/tts/emotion/output` snapshots, TracingProxy exports a differently formatted OTel trace ID, service modules update metrics directly, and inspection probes unrelated Chroma paths. The existing local database demonstrates the failure mode: most service spans are not joined to their root trace, golden nodes are absent, and many traces remain `running`.

The accepted constraints are:

- Local observation must remain complete without OTel Collector, Grafana, Langfuse, or network access.
- `task_id` is the canonical identity for a conversation trace.
- Development may retain conversation text; golden and production default to redacted persistence.
- Existing stats data has no retention value and may be discarded.
- The first release covers text, voice, and shared memory. Other runtime branches receive a stable future integration contract but are not instrumented in this change.
- Chat behavior, event payloads, provider selection, graph ordering, and memory policy are not redesigned by this change.

## Goals / Non-Goals

**Goals:**

- Establish one authoritative local ledger for traces, operations, and events.
- Make the recorded topology match the graph and service calls that actually executed.
- Preserve parent-child relationships across normal awaits and background memory queues.
- Derive typed turn outcomes from final state and delivery evidence.
- Separate recording, querying, metrics, OTLP export, dashboard, and inspection through ports.
- Guarantee that a completed turn is queryable locally before the request lifecycle returns.
- Make privacy policy explicit, testable, and profile-aware.
- Make health and inspection validate real runtime components and stored evidence.

**Non-Goals:**

- Changing the golden or standard dialogue algorithms.
- Turning OTel, Prometheus, Grafana, or Langfuse into required dependencies.
- Migrating or repairing existing `data/stats.db` records.
- Recording prompts, model reasoning, audio bytes, secrets, or unrestricted payload JSON.
- Instrumenting singing, Minecraft, Bilibili, explicit meme effects, or every maintenance job in the first release.
- Implementing distributed multi-process trace aggregation; the first ledger is a single-process local owner.

## Decisions

### 1. SQLite ledger is the only local source of truth

Create `animetta.observability` with dependency-light domain models and ports. `SQLiteObservationLedger` implements both `ObservationRecorder` and `ObservationQuery`; business modules receive the recorder port, while API, dashboard, and inspection receive the query port.

OTel and Prometheus are downstream mirrors of committed observation records. They never write back to SQLite. This replaces the current callback/snapshot/exporter triple-write design.

Alternative considered: make OTel the source of truth and export into SQLite. Rejected because SDK/exporter lifecycle, ID conversion, and flush behavior would make local completeness dependent on tracing infrastructure.

### 2. Canonical identity and context are explicit domain values

`ObservationContext` contains `trace_id`, `operation_id`, `parent_operation_id`, `message_id`, `conversation_id`, `session_id`, and privacy mode. The root `trace_id` is exactly the validated `task_id`; no UUID-to-hex conversion occurs in the ledger.

The active context is propagated with `ContextVar`. `ObservationCarrier` is a serializable subset containing trace and parent operation identities for queued work. SharedMemoryRuntime stores the carrier on `ConversationTurn` and propagates it into ingestion and index operations.

Alternative considered: infer the active trace from session ID or latest running trace. Rejected because sessions can contain multiple turns and background work can outlive the visible request.

### 3. The ledger schema models facts, not a tracing vendor

The replacement database contains:

- `observation_traces`: identity, profile, input type, privacy mode, lifecycle timestamps, typed outcome, error/degradation code, redacted content facts, and allowlisted metadata.
- `observation_operations`: parented workflow/service/memory/delivery operations with layer, actual name, critical-path flag, timestamps, status, provider/model, error code, and allowlisted attributes.
- `observation_events`: instantaneous ingress, egress, interrupt, queue, and lifecycle evidence with direction, phase, payload size, and identity-valid flag.
- `inspection_reports`: frozen inspection report data, retained behind the query/storage port.

Foreign keys are enabled. A trace cannot finalize while critical-path operations remain running. Background operations may be appended after trace finalization when `critical_path=false`.

### 4. Real graph nodes are wrapped at registration

`instrument_node(name, node, recorder)` wraps the exact callable registered with StateGraph. It starts and finishes one workflow operation under the active trace and records returned state errors or typed degradation. The builder supplies the actual registration name for both golden and standard graphs.

There is no `KNOWN_NODES` allowlist and no synthetic fallback snapshot. A node missing from the ledger is therefore a real instrumentation defect that tests can detect.

Alternative considered: continue using generic LangChain callbacks. Rejected because callback serialization names are version-sensitive and have already diverged from the compiled graph.

### 5. Services, delivery, and memory use adapters over the recorder port

- `InstrumentedServiceProxy` records async methods and async generators as service operations. Factories may wrap providers without importing SQLite, OTel, or Prometheus.
- `ObservedChatDelivery` or an injected recorder in ChatDelivery records the event name, phase, identity validation, payload byte size, and emit outcome. Payload content is not copied.
- `ObservedMemoryRuntime` integration records recall, enqueue acceptance/rejection, ingestion, SQLite commit, outbox processing, and Chroma indexing. Memory health reads `SharedMemoryRuntime.health()`.
- `log_node_error()` becomes a compatibility facade over the active recorder and never accepts an optional externally supplied trace ID.

### 6. Trace outcome is a deterministic reduction

Trace outcomes are `success`, `degraded`, `failed`, `cancelled`, and `aborted`.

- `success`: a usable final response and all required delivery events completed.
- `degraded`: usable text was delivered but an optional capability such as TTS, translation, recall, or memory processing degraded.
- `failed`: validation, workflow, provider, or required delivery failure prevented a usable completed response.
- `cancelled`: user interrupt or task cancellation terminated the turn.
- `aborted`: startup recovery found a trace left running by process termination.

Operation statuses are `success`, `skipped`, `degraded`, `error`, and `cancelled`. The reducer evaluates final state plus committed delivery evidence; absence of an exception is not sufficient for success.

### 7. One writer task serializes SQLite and completion uses a barrier

The ledger owns a bounded asyncio queue and a single writer task. Recording methods enqueue immutable commands. Root trace creation awaits its commit; ordinary operation/event records are queued; trace finalization enqueues a flush barrier and awaits it before returning.

Queue exhaustion never blocks indefinitely. Critical root/finalization records use a reserved path and surface a ledger-unavailable error; non-critical mirror/diagnostic records may be dropped with an internal health counter. Shutdown drains with a bounded timeout and marks unfinished traces aborted on next startup.

Alternative considered: one transaction per callback. Rejected because high-frequency delivery and service events would add avoidable contention to the response path.

### 8. Privacy is applied before persistence

`ObservationContentPolicy` runs before a ledger command is created. Development `full` mode may persist user and final assistant text. Golden and production `redacted` mode persist character/byte lengths, a salted SHA-256 digest, language, and allowlisted outcome metadata only.

The salt is installation-local configuration and is never returned by APIs. Internal prompts, reasoner/composer objects, tool secrets, tokens, audio, subtitle payloads, and unrestricted exception text are never persisted. Error text is normalized to a bounded code plus sanitized summary.

### 9. Mirrors consume committed records

After a SQLite transaction commits, the ledger publishes immutable records to registered `ObservationMirror` consumers.

- PrometheusMirror updates local prometheus_client counters and histograms with bounded label sets.
- OTelMirror creates equivalent spans/events using the canonical trace ID as an attribute and preserves the ledger operation hierarchy. OTLP batching remains optional and network failures only affect mirror health.

Mirror callbacks run outside the SQLite transaction and cannot fail or delay trace finalization. Metrics inspection verifies counter deltas generated by a controlled observation, not just metric-name presence.

### 10. Query APIs replace private database access

`ObservationQuery` exposes overview, node/operation aggregates, recent traces, trace detail/tree, event evidence, inspection reports, and ledger health. Starlette stats routes depend on this port and preserve existing endpoint paths where practical while returning versioned DTOs.

Dashboard terminology changes from synthetic spans to operations and displays outcome, real topology, critical-path duration, post-turn background work, delivery events, provider/model, and degradation reasons.

Inspection uses only public runtime/query ports. The golden smoke verifies its input identity, required delivery events, stored trace, expected golden workflow operations, exactly two real LLM service operations, real TTS or explicit degradation, and no forbidden memory write. Standard and voice integration tests verify their own actual topologies.

### 11. Configuration and lifecycle ownership are application-scoped

The server constructs one ledger beside SharedMemoryRuntime, starts it before route work can be accepted, injects recorder/query ports into dependent components, and shuts it down after sessions and memory workers have drained.

`observability.yaml` controls local enablement, database path, queue size, privacy mode overrides, and mirror enablement. The local ledger defaults on; OTLP defaults off. Disabling local observation installs a NoOp recorder but health clearly reports observation disabled rather than pretending it is healthy.

## Risks / Trade-offs

- [Cross-cutting migration touches many boundaries] → Introduce ports and adapters first, then switch one producer/consumer at a time while contract tests compare evidence.
- [Queue loss during abrupt process termination] → Await root/final barriers, use WAL, bound shutdown drain, and recover stale traces as aborted.
- [Background memory operations arrive after turn finalization] → Permit non-critical post-turn operations and expose their pending/completed state separately from response latency.
- [Metric label explosion] → Use fixed enums and allowlisted provider/model/tool labels; never label with IDs or content.
- [Instrumentation wrapper changes callable signatures] → Preserve signatures with `functools.wraps` and add graph compilation tests for both profiles.
- [Privacy regression] → Centralize content policy before persistence and test the raw SQLite rows in golden mode.
- [Mirror recursion or self-observation] → Ledger/mirror internals never record through the public recorder while handling a committed record.
- [Existing stats clients expect old DTOs] → Version trace DTOs, retain endpoint paths for one release, and update the bundled dashboard atomically.

## Migration Plan

1. Add observability domain, ports, NoOp implementations, schema, ledger lifecycle, and isolated tests without changing producers.
2. Add graph/service/delivery/memory adapters and run them in shadow mode against a temporary ledger during tests.
3. Switch orchestrator trace ownership and graph node registration to the ledger; remove synthetic snapshots and callback StatsStore writes.
4. Switch service factories, ChatDelivery, memory middleware, and SharedMemoryRuntime to recorder adapters and carriers.
5. Replace stats/query APIs, dashboard DTOs, inspection persistence, component health, and smoke assertions.
6. Replace direct metrics calls with PrometheusMirror; convert OTel exporter into an optional one-way mirror.
7. Remove StatsCallbackHandler, StatsSpanExporter SQLite behavior, old StatsStore trace/span schema, and direct private `_db` probes.
8. Delete/recreate `data/stats.db`, run schema validation, focused tests, full test suites, and the Docker startup/health/log protocol.

Rollback is configuration-first while migration is in progress: keep the old reader behind a temporary feature flag until the new query API and dashboard are verified. Once the old database is intentionally discarded and the change is accepted, rollback restores the previous release binary and creates a fresh legacy database; no new ledger data is migrated backward.

## Open Questions

None block implementation. Initial defaults are local ledger enabled, `data/observations.db`, WAL mode, queue capacity 4096, development `full` privacy, golden/production `redacted` privacy, and OTLP disabled.
