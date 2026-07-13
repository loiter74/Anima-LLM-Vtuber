## Purpose
Defines the accepted behavior and requirements for the otel-tracing capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: Service calls produce OTel spans
Every observed LLM, TTS, ASR, and VAD service call SHALL first produce a local service operation. When the OTel mirror is enabled, each committed service operation SHALL also produce an OpenTelemetry span with equivalent name, status, timing, and allowlisted attributes.

#### Scenario: LLM call is observed locally
- **WHEN** reasoner calls `llm.chat_messages`
- **THEN** the ledger SHALL contain a completed `llm.chat_messages` service operation

#### Scenario: OTel mirror is enabled
- **WHEN** a committed `tts.synthesize` operation is published to the enabled OTel mirror
- **THEN** a span named `tts.synthesize` SHALL be exported with matching status and duration

#### Scenario: Service error is captured
- **WHEN** an observed service method raises
- **THEN** the local operation SHALL have status `error` and a structured error code
- **AND** any mirrored OTel span SHALL have status ERROR without unrestricted exception content

### Requirement: Span hierarchy matches call tree
Local operations SHALL form the authoritative parent-child tree matching workflow node, service method, and sub-operation execution. Any OTel mirror SHALL reproduce this hierarchy from committed operation IDs rather than deriving a second local trace tree.

#### Scenario: Nested service operation
- **WHEN** `reasoner` invokes `llm.chat_messages`
- **THEN** the local service operation SHALL have the reasoner operation as parent
- **AND** the mirrored OTel span SHALL preserve the same logical parent relationship

#### Scenario: Context propagation across async boundaries
- **WHEN** a service or memory operation resumes after an await or from an ObservationCarrier
- **THEN** it SHALL retain the originating trace and parent identities

### Requirement: Spans written to StatsStore AND exported via OTLP
All completed operations SHALL be written once to the local observation ledger. When OTLP is configured, an OTel mirror SHALL export committed records asynchronously. OTLP failure SHALL NOT alter, retry, or duplicate the local record.

**Reason**: Replaced by a single-writer local ledger and one-way optional mirrors; dual SQLite writers caused orphan spans and inconsistent topology.

**Migration**: Remove SQLite writes from StatsSpanExporter. Commit all operations to SQLiteObservationLedger, then mirror committed operations to OTLP when enabled.

#### Scenario: OTLP disabled
- **WHEN** `otlp.enabled` is false
- **THEN** local operations SHALL remain complete and no OTLP connection SHALL be attempted

#### Scenario: OTLP endpoint unreachable
- **WHEN** OTLP is enabled but unavailable
- **THEN** mirror health SHALL become degraded
- **AND** local observation and request processing SHALL continue

### Requirement: Dashboard shows span tree
The existing stats dashboard SHALL display individual trace detail as a span tree / flame chart.

#### Scenario: View trace tree
- **WHEN** user clicks a trace in the trace list
- **THEN** the detail view SHALL show all spans organized by parent_span_id as a nested tree
- **THEN** each span SHALL display name, duration_ms, and status

### Requirement: Tracing can be disabled
External OTel tracing SHALL be independently disableable without disabling the local observation ledger. Local observation MAY be disabled only through its own explicit configuration.

#### Scenario: OTel tracing is disabled
- **WHEN** OTLP and OTel mirroring are disabled
- **THEN** no OTel spans SHALL be exported
- **AND** local traces and operations SHALL still be recorded

### Requirement: OTLP configuration in observability.yaml
The `config/observability.yaml` SHALL include an `otlp` section with `enabled`, `endpoint`, and `protocol` fields. The default value for `enabled` SHALL be `false` (opt-in).

#### Scenario: OTLP config loaded
- **WHEN** the backend starts
- **THEN** the OTLP configuration SHALL be read from `config/observability.yaml` under the `otlp` key
- **THEN** the default `enabled` value SHALL be `false` (OTLP export opt-in)
- **THEN** the default endpoint SHALL be `http://localhost:4317` (gRPC)
- **THEN** the config file SHALL include an inline comment explaining that `enabled: true` requires the observability stack to be running

### Requirement: OTel Collector, Prometheus, Tempo, Grafana via docker-compose
The observability stack SHALL be deployable with a single `docker-compose up -d` command.

#### Scenario: One-command startup
- **WHEN** user runs `docker-compose -f observability/docker-compose.yml up -d`
- **THEN** four containers SHALL start: otel-collector, prometheus, tempo, grafana
- **THEN** the OTel Collector SHALL listen on port 4317 (gRPC) and 4318 (HTTP) for OTLP data
- **THEN** Prometheus SHALL scrape the OTel Collector's `:8889/metrics` endpoint
- **THEN** Tempo SHALL receive traces via OTLP on port 4317
- **THEN** Grafana SHALL be accessible at `http://localhost:3000`

### Requirement: BatchSpanProcessor for OTLP export
The OTLP exporter SHALL use `BatchSpanProcessor` (not SimpleSpanProcessor) to avoid blocking the request path on network I/O.

#### Scenario: Batch export configuration
- **WHEN** OTLP export is enabled
- **THEN** spans SHALL be batched and exported in the background
- **THEN** the request path SHALL NOT be blocked by span export
