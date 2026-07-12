## Why

Animetta currently records one conversation through several competing paths: LangGraph callbacks, synthetic StatsStore snapshots, OpenTelemetry service spans, direct Prometheus calls, and inspection-specific probes. These paths disagree on trace identity, node topology, success semantics, and memory health, so the local dashboard can report orphan spans, stale node names, false-positive metrics, and successful traces for failed turns.

The project needs one local-first observation ledger that remains complete without an OTel Collector or external service, while keeping OTLP, Prometheus, Grafana, and inspection as decoupled consumers of the same committed facts.

## What Changes

- Introduce a dependency-light observability domain with `ObservationContext`, trace outcomes, operation statuses, event records, recorder/query ports, and ContextVar propagation.
- Add a SQLite local observation ledger as the only authoritative trace store, using `task_id` as the canonical trace identity and recording real workflow nodes, service operations, delivery events, and asynchronous memory work.
- Add explicit privacy modes: development may retain visible conversation text; golden/production defaults to redacted length, salted hash, and allowlisted operational metadata.
- Instrument LangGraph registration, service proxies, ChatDelivery, and SharedMemoryRuntime through observability ports instead of importing StatsStore, OTel, or Prometheus directly.
- Derive trace outcome from typed final state and required delivery events, distinguishing success, degradation, failure, cancellation, and process abort.
- Replace StatsStore trace/span writes, synthetic node snapshots, and the SQLite-writing `StatsSpanExporter` with ledger-backed query APIs and optional one-way OTLP/Prometheus mirrors.
- Reset the obsolete stats database instead of migrating historical traces and orphan spans.
- Update health and inspection checks to validate the real ledger, real shared-memory runtime, correlated task trace, actual provider calls, graph topology, delivery events, and memory side effects.
- Limit the first implementation to text conversation, voice conversation, and shared memory; define a stable observation carrier for later singing, Minecraft, Bilibili, and explicit-meme adoption.

## Capabilities

### New Capabilities

- `local-observability-ledger`: Defines the canonical local trace, operation, and event ledger; context propagation; lifecycle; query boundary; asynchronous-memory correlation; and local-first availability guarantees.
- `observation-privacy-policy`: Defines development/full-content and golden-production/redacted persistence modes with strict metadata allowlists.

### Modified Capabilities

- `observability-config`: Make the local ledger independently configurable and keep OTLP strictly optional.
- `otel-tracing`: Change OTel from a second SQLite writer into a one-way mirror of committed ledger records while preserving real parent-child service spans.
- `otel-metrics`: Derive node, service, RAG, session, and tool metrics from committed observation records and actual compiled node names.
- `prometheus-metrics-endpoint`: Require metrics to reflect recorded activity, not merely pre-registered metric names.
- `node-error-logging`: Record structured errors through the active observation context without direct StatsStore access or optional trace IDs.
- `component-health-check`: Probe the actual local ledger and application-owned SharedMemoryRuntime instead of unrelated Chroma paths or permissive placeholders.
- `inspection-scheduler`: Persist inspection reports through the observation query/storage boundary and report mirror/runtime health without private database access.
- `pipeline-smoke-test`: Verify one identity-correlated real turn against its stored trace, real node/service operations, delivery events, provider identity, and prohibited memory effects.
- `grafana-dashboards`: Use real profile-specific node names and ledger-derived metrics rather than the legacy fixed pipeline.

## Impact

- Backend: new `src/animetta/observability/` package; changes to graph builder/orchestrator, service instrumentation, ChatDelivery, SharedMemoryRuntime, startup/shutdown, health, inspection, and stats APIs.
- Storage: replacement local SQLite schema for traces, operations, events, and inspection reports; existing `data/stats.db` data is discarded.
- Frontend: dashboard query DTOs and trace-tree rendering update to consume ledger terminology and outcome states.
- External observability: OTLP remains opt-in; Prometheus and Grafana remain optional mirrors and never gate local observation correctness.
- Compatibility: public chat Socket.IO contracts and business response semantics remain unchanged; legacy stats database internals are intentionally removed.
