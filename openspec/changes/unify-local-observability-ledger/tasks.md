## 1. Baseline and Contracts

- [x] 1.1 Record the current unrelated Voyager/Minecraft worktree paths and ensure observability changes do not modify or stage them
- [x] 1.2 Add failing domain contract tests for canonical task identity, trace/operation statuses, immutable records, and ObservationCarrier serialization
- [x] 1.3 Add failing architecture tests that forbid observability domain/ports imports from orchestration, services, SQLite, OTel, and Prometheus implementations
- [x] 1.4 Add failing profile privacy tests that inspect raw persistence commands for development full mode and golden/production redacted mode

## 2. Observation Domain and Ports

- [x] 2.1 Create the `animetta.observability` package with dependency-light trace, operation, event, health, and outcome domain models
- [x] 2.2 Define ObservationRecorder, ObservationQuery, ObservationReportStore, and ObservationMirror protocols plus NoOp implementations
- [x] 2.3 Implement ObservationContext ContextVar attach/detach helpers and serializable ObservationCarrier propagation
- [x] 2.4 Implement structured error classification and bounded attribute allowlists
- [x] 2.5 Implement ObservationContentPolicy with profile defaults, salted digests, payload exclusion, and sanitized error summaries
- [x] 2.6 Make all domain, port, context, and privacy contract tests pass

## 3. SQLite Local Ledger

- [x] 3.1 Add failing schema tests for observation_traces, observation_operations, observation_events, inspection_reports, indexes, and enabled foreign keys
- [x] 3.2 Add failing lifecycle tests for root durability, parent validation, finalization barriers, post-turn non-critical operations, and stale-trace abort recovery
- [x] 3.3 Add failing queue tests for bounded capacity, critical record reservation, non-critical drops, writer failure, health counters, and shutdown draining
- [x] 3.4 Implement SQLiteObservationLedger schema creation, WAL/busy-timeout setup, and schema versioning at `data/observations.db`
- [x] 3.5 Implement the single writer task, immutable write commands, committed-record publication, and flush barriers
- [x] 3.6 Implement trace, operation, event, inspection-report, health, and abort-recovery recorder methods
- [x] 3.7 Implement ObservationQuery overview, aggregates, recent traces, detail/tree, events, post-turn state, reports, and health methods
- [x] 3.8 Make ledger schema, lifecycle, queue, recovery, and query tests pass

## 4. Application Lifecycle and Dependency Injection

- [x] 4.1 Add failing startup/shutdown tests proving one application-owned ledger starts before route work and drains after sessions and memory workers
- [x] 4.2 Extend observability configuration with ledger path, queue, drain, privacy, Prometheus mirror, and OTLP mirror settings while keeping OTLP opt-in
- [x] 4.3 Construct and inject recorder/query/report ports from the ASGI server lifecycle without service-locator imports in business modules
- [x] 4.4 Expose cached observation health and install NoOp ports when explicitly disabled
- [x] 4.5 Make lifecycle, configuration-default, disabled-mode, and dependency-direction tests pass

## 5. Real LangGraph and Turn Instrumentation

- [x] 5.1 Add failing graph tests that compare the golden and standard compiled node sets with their committed workflow operations
- [x] 5.2 Add failing turn tests proving trace_id equals task_id and all workflow operations share that identity without synthetic snapshots
- [x] 5.3 Implement `instrument_node(name, node, recorder)` with signature preservation, parent context, returned-state status classification, cancellation, and exception handling
- [x] 5.4 Register every golden and standard node through the instrumentation wrapper while preserving graph topology and tool-loop behavior
- [x] 5.5 Move root trace creation/finalization into an injected conversation observer at the normalized command/orchestrator boundary
- [x] 5.6 Implement deterministic trace outcome reduction from final state and committed required-delivery evidence
- [x] 5.7 Remove StatsCallbackHandler injection, KNOWN_NODES filtering, and orchestrator synthetic snapshot generation
- [x] 5.8 Make graph topology, canonical identity, soft-failure, degradation, cancellation, and flush-before-return tests pass

## 6. Service, Delivery, and Memory Adapters

- [x] 6.1 Add failing service-proxy tests for async methods, async generators, nested parentage, provider/model attributes, errors, cancellation, and privacy
- [x] 6.2 Implement InstrumentedServiceProxy over ObservationRecorder and switch LLM/TTS/ASR/VAD factories without importing ledger, OTel, or Prometheus implementations
- [x] 6.3 Add failing ChatDelivery tests for ingress/egress identity, event phase, payload size, emit success/failure, and audio/payload exclusion
- [x] 6.4 Instrument ChatDelivery through the recorder port without changing public Socket.IO event contracts
- [x] 6.5 Add failing memory tests for recall, queue acceptance/rejection, ObservationCarrier, ingestion, SQLite commit, outbox, Chroma indexing, and critical_path=false
- [x] 6.6 Carry observation identity through ConversationTurn and SharedMemoryRuntime workers without changing memory visibility, scope, retention, or ranking semantics
- [x] 6.7 Instrument MemoryMiddleware and SharedMemoryRuntime using public adapters and expose actual runtime health
- [x] 6.8 Convert log_node_error into an active-context recorder facade and remove optional trace-ID/StatsStore coupling
- [x] 6.9 Make service, delivery, memory, and structured-error integration tests pass

## 7. Prometheus and OTel Mirrors

- [x] 7.1 Add failing Prometheus mirror tests for exactly-once committed-record updates, actual node labels, typed outcomes, RAG/service durations, active sessions, and bounded cardinality
- [x] 7.2 Implement PrometheusMirror as a committed-record consumer and remove direct business-module metric updates
- [x] 7.3 Add a controlled-delta metrics inspection test that fails when names exist but values do not change
- [x] 7.4 Add failing OTel mirror tests for one-way export, hierarchy preservation, optional startup, sanitized attributes, batching, and unreachable-collector degradation
- [x] 7.5 Implement OTelMirror and remove SQLite writes from StatsSpanExporter
- [x] 7.6 Ensure mirror failures update mirror health without recursively recording themselves or delaying ledger finalization
- [x] 7.7 Make Prometheus endpoint, controlled-delta, OTel-disabled, OTel-enabled, and mirror-failure tests pass

## 8. Query API and Local Dashboard

- [x] 8.1 Define versioned ledger-backed DTOs for overview, trace list, trace detail, operation tree, events, post-turn work, outcomes, and health
- [x] 8.2 Add failing API tests proving stats routes use ObservationQuery and never access private SQLite fields
- [x] 8.3 Replace StatsStore-backed stats route implementations while preserving public endpoint paths for the bundled dashboard
- [x] 8.4 Update the frontend dashboard store and trace detail view for typed outcomes, actual operation hierarchy, critical-path duration, delivery events, providers, degradation, and background memory work
- [x] 8.5 Add frontend unit tests for golden and standard topology rendering, redacted content, degraded traces, and post-turn operation updates
- [x] 8.6 Make backend stats API and frontend dashboard tests pass

## 9. Health and Inspection Alignment

- [x] 9.1 Add failing component-health tests for the real ledger, ServicePool readiness/provider identity, SharedMemoryRuntime readiness/backlog/errors, canonical SQLite, and actual metrics delta
- [x] 9.2 Replace direct Chroma clients, unrelated storage paths, permissive uninitialized success, and private `_db` probes with injected runtime/query health
- [x] 9.3 Persist and query inspection reports through ObservationReportStore/ObservationQuery
- [x] 9.4 Add a failing real Socket.IO golden inspection test for negative-probe absence, identity-correlated trace lookup, actual golden nodes, exactly two non-mock LLM calls, TTS ready/degraded evidence, and prohibited memory writes
- [x] 9.5 Add standard-text and voice observation integration tests that validate their executed topology without a fixed legacy node list
- [x] 9.6 Update pipeline and metrics inspection implementations to compare client events with committed ledger events and controlled metric deltas
- [x] 9.7 Make health, report persistence, golden smoke, standard smoke, voice smoke, and cleanup/timeout tests pass

## 10. Legacy Removal and Data Reset

- [x] 10.1 Remove legacy StatsStore trace/span/conversation-turn responsibilities after all readers and writers use observation ports
- [x] 10.2 Remove StatsCallbackHandler, synthetic snapshot helpers, SQLite-exporting StatsSpanExporter behavior, and direct business metrics imports
- [x] 10.3 Replace or remove legacy dashboard node assumptions and obsolete stats schema migrations
- [x] 10.4 Add a deterministic reset/bootstrap command for deleting obsolete `data/stats.db` data and creating the new observation schema
- [x] 10.5 Run dependency and search audits proving there is one trace writer, no private inspection `_db` access, no unrelated Chroma probe paths, and no direct business Prometheus updates

## 11. Verification and Release Gates

- [x] 11.1 Run focused observability, graph, service, delivery, memory, API, inspection, and frontend unit tests
- [x] 11.2 Run the full backend pytest suite, frontend Vitest suite, Ruff, and configured type checks; classify and resolve every failure caused by this change
- [x] 11.3 Start the CPU or GPU Docker deployment through the required sub-agent protocol, poll `/health`, `/ready`, frontend port 80, and `/metrics`, and scan logs for ERROR or Traceback
- [x] 11.4 Use the required QA skill with a fresh Playwright capture to verify local dashboard overview, golden trace tree, redacted detail, degradation display, and post-turn memory operations
- [x] 11.5 Run a real correlated text turn and voice turn, then query raw SQLite, API DTOs, Prometheus values, and optional OTLP evidence to prove one canonical trace and zero orphan operations
- [x] 11.6 Validate the OpenSpec change and record final evidence for every requirement before marking tasks complete
