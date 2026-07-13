# local-observability-ledger Specification

## Purpose
TBD - created by archiving change unify-local-observability-ledger. Update Purpose after archive.
## Requirements
### Requirement: Local ledger is the authoritative observation store
The system SHALL persist conversation traces, operations, and events to a local SQLite observation ledger that remains fully functional without an OTel Collector, Grafana, Langfuse, or network access. No other exporter or callback SHALL write trace facts back into the ledger.

#### Scenario: External observability is unavailable
- **WHEN** OTLP, Grafana, and external observability services are disabled or unreachable
- **THEN** a completed local conversation SHALL still be queryable with its outcome, actual operations, delivery events, and durations

#### Scenario: Optional mirror fails
- **WHEN** an enabled OTel or Prometheus mirror raises while consuming a committed record
- **THEN** the local ledger record SHALL remain committed and the conversation result SHALL be unaffected

### Requirement: Task identity is canonical end to end
The ledger SHALL use the validated chat `task_id` verbatim as the root `trace_id` and SHALL store the associated `message_id`, `conversation_id`, and `session_id`. It SHALL NOT derive a second UUID or change the trace ID textual format.

#### Scenario: Canonical text turn starts
- **WHEN** a normalized chat command with `task_id=T` enters orchestration
- **THEN** the ledger SHALL create exactly one trace whose primary key is `T`
- **AND** every operation and event for that turn SHALL reference `T`

#### Scenario: Service operation is queried
- **WHEN** the trace detail for `T` is requested after an LLM call
- **THEN** the LLM operation SHALL be returned under the same `T` rather than as an orphan operation

### Requirement: Recorded workflow topology matches actual execution
Every LangGraph node that executes SHALL create one workflow operation using the exact node name registered in the compiled graph. The system SHALL NOT use a fixed legacy node allowlist or synthesize fallback node snapshots.

#### Scenario: Golden turn executes
- **WHEN** the golden graph completes a normal text turn
- **THEN** the ledger SHALL contain `conversation_start`, `personality`, `reasoner`, `anima_composer`, `response_guard`, `reply_output`, `tts`, `emotion`, `performance_output`, and `conversation_finalizer` workflow operations in execution order

#### Scenario: Standard turn executes
- **WHEN** the standard graph completes a normal text turn
- **THEN** the ledger SHALL contain only the standard nodes that actually executed, including any real tool-loop repetitions

### Requirement: Operation hierarchy follows runtime calls
Workflow, service, memory, and delivery operations SHALL preserve actual parent-child relationships using the active ObservationContext propagated through ContextVar.

#### Scenario: Reasoner calls the LLM
- **WHEN** the `reasoner` workflow node invokes `llm.chat_messages`
- **THEN** the service operation SHALL be a child of the `reasoner` operation

#### Scenario: Context crosses await boundaries
- **WHEN** an observed service call awaits network I/O and resumes
- **THEN** it SHALL retain its original trace and parent operation identities

### Requirement: Trace outcomes reflect business and delivery evidence
The ledger SHALL finalize a trace as exactly one of `success`, `degraded`, `failed`, `cancelled`, or `aborted`. Outcome reduction SHALL evaluate final workflow state and required delivery evidence; absence of an exception alone SHALL NOT imply success.

#### Scenario: Text succeeds and TTS degrades
- **WHEN** usable text and terminal control are delivered but TTS returns an allowed degradation
- **THEN** the trace outcome SHALL be `degraded`
- **AND** the TTS operation SHALL identify its structured degradation reason

#### Scenario: Graph returns an error state
- **WHEN** graph invocation returns without raising but no usable response is produced and final state contains an error
- **THEN** the trace outcome SHALL be `failed`

#### Scenario: Process terminates mid-turn
- **WHEN** startup finds a trace left in running state by a prior process
- **THEN** the ledger SHALL mark it `aborted`

### Requirement: Background memory work remains correlated without extending response latency
The system SHALL attach a serializable ObservationCarrier to accepted memory work. Ingestion, canonical SQLite commit, outbox handling, and Chroma indexing MAY append non-critical operations to a finalized trace and SHALL NOT extend the trace's critical-path duration.

#### Scenario: Turn is queued for ingestion
- **WHEN** output submits an accepted ConversationTurn
- **THEN** the queue event SHALL record its original trace and parent operation identities

#### Scenario: Ingestion completes after conversation end
- **WHEN** the memory worker commits and indexes the turn after terminal chat delivery
- **THEN** those operations SHALL appear under the originating trace with `critical_path=false`
- **AND** the previously finalized response duration SHALL remain unchanged

### Requirement: Ledger lifecycle is durable and bounded
The ledger SHALL serialize writes through one bounded writer queue, await root-trace creation, and await a flush barrier when finalizing a trace. Shutdown SHALL drain for a bounded interval and expose queue, drop, writer-error, and stale-trace health.

#### Scenario: Trace finalization returns
- **WHEN** the orchestrator finishes a trace
- **THEN** all critical-path records queued before the finalization barrier SHALL be queryable immediately

#### Scenario: Queue pressure occurs
- **WHEN** non-critical observation commands exceed queue capacity
- **THEN** the ledger SHALL increment a drop counter and report degraded health without blocking the business pipeline indefinitely

### Requirement: Public query port owns observation reads
Dashboard, stats APIs, inspection, and health code SHALL query observations through the ObservationQuery port and SHALL NOT access SQLite connection internals.

#### Scenario: Trace tree is requested
- **WHEN** the stats API requests a trace detail
- **THEN** ObservationQuery SHALL return the trace, parented operations, events, and post-turn state without exposing a database handle
