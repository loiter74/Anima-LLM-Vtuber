## Purpose
Defines the accepted behavior and requirements for the otel-tracing capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Service calls produce OTel spans
Every service method call (LLM.chat_stream, TTS.synthesize, ASR.transcribe, VAD.detect_speech) SHALL automatically produce an OpenTelemetry span.

#### Scenario: LLM chat_stream traced
- **WHEN** llm_node calls service.chat_stream("你好")
- **THEN** a span named "llm.chat_stream" SHALL be created with start_time, end_time, and duration

#### Scenario: TTS synthesize traced
- **WHEN** tts_node calls service.synthesize("你好")
- **THEN** a span named "tts.synthesize" SHALL be created

#### Scenario: Service error captured
- **WHEN** a service method raises an exception
- **THEN** the span SHALL have status=ERROR and record the exception

### Requirement: Span hierarchy matches call tree
Spans SHALL form a parent-child tree matching the actual call hierarchy: LangGraph node → service method → sub-operations.

#### Scenario: Nested span creation
- **WHEN** llm_node calls chat_stream which internally calls an HTTP API
- **THEN** the "llm.chat_stream" span SHALL have as parent the "llm_node" span
- **THEN** each sub-operation SHALL be a child span of "llm.chat_stream"

#### Scenario: Context propagation across async boundaries
- **WHEN** a service method is called from an async context
- **THEN** the span SHALL correctly inherit the parent trace context via ContextVar

### Requirement: Spans written to StatsStore AND exported via OTLP
All completed spans SHALL be written to the StatsStore SQLite database via `StatsSpanExporter` AND exported to an OTel Collector via `OTLPSpanExporter` when the OTLP endpoint is configured.

#### Scenario: Dual export active
- **WHEN** `config/observability.yaml` has `otlp.enabled: true` and a valid `endpoint`
- **THEN** `BatchSpanProcessor(OTLPSpanExporter)` SHALL be added to the TracerProvider alongside the existing `SimpleSpanProcessor(StatsSpanExporter)`
- **THEN** each completed span SHALL be written to BOTH SQLite and the OTLP endpoint

#### Scenario: OTLP disabled
- **WHEN** `config/observability.yaml` has `otlp.enabled: false`
- **THEN** only `StatsSpanExporter` SHALL be active (single export to SQLite)
- **THEN** no gRPC connection to the Collector SHALL be attempted

#### Scenario: OTLP endpoint unreachable
- **WHEN** OTLP export is enabled but the Collector is not running
- **THEN** the system SHALL log a warning and continue (graceful degradation)
- **THEN** spans SHALL still be written to StatsStore SQLite

#### Scenario: Batch writing
- **WHEN** many spans end in quick succession
- **THEN** they SHALL be batched and written at once (max 512 spans or 5s interval)

### Requirement: Dashboard shows span tree
The existing stats dashboard SHALL display individual trace detail as a span tree / flame chart.

#### Scenario: View trace tree
- **WHEN** user clicks a trace in the trace list
- **THEN** the detail view SHALL show all spans organized by parent_span_id as a nested tree
- **THEN** each span SHALL display name, duration_ms, and status

### Requirement: Tracing can be disabled
The tracing infrastructure SHALL support being disabled via configuration without code changes.

#### Scenario: Disable tracing
- **WHEN** tracing is disabled in config
- **THEN** NoOpTracerProvider SHALL be used (zero overhead)
- **THEN** no spans SHALL be created or written

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
