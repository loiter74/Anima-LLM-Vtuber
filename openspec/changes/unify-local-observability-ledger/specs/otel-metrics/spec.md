## MODIFIED Requirements

### Requirement: OTel MeterProvider initialized
The system SHALL keep local Prometheus metric production independent from OTel. An OTel MeterProvider and OTLP metric reader SHALL be initialized only when OTel metric mirroring is explicitly enabled; committed local observation records SHALL remain the source of metric updates.

#### Scenario: OTLP disabled
- **WHEN** the backend starts with `otlp.enabled: false`
- **THEN** local prometheus_client metrics SHALL update from committed observation records
- **AND** no OTLP metric reader SHALL connect to a collector

#### Scenario: OTLP enabled
- **WHEN** the backend starts with `otlp.enabled: true`
- **THEN** committed observation metrics SHALL also be mirrored to the configured OTel endpoint

### Requirement: LangGraph node duration histogram
The system SHALL record `anima_node_duration_seconds` for every committed workflow operation, labeled by the exact compiled `node_name` and runtime profile. Labels SHALL use a bounded set and SHALL NOT contain trace, session, or content values.

#### Scenario: Golden pipeline completes
- **WHEN** a golden turn commits its workflow operations
- **THEN** duration observations SHALL exist for the actual golden node names including `reasoner`, `anima_composer`, `reply_output`, and `performance_output`

#### Scenario: Tool loop repeats
- **WHEN** the standard graph executes a node more than once
- **THEN** each committed execution SHALL contribute one duration observation

### Requirement: LangGraph node error counter
The system SHALL increment `anima_node_errors_total` from committed workflow operations whose status is `error`, labeled by actual node name and structured error type.

#### Scenario: Soft workflow failure is recorded
- **WHEN** a node returns a typed error state without raising and the operation is committed as error
- **THEN** the corresponding node error counter SHALL increment

### Requirement: RAG retrieval metrics
The system SHALL derive RAG duration and retrieved-item metrics from committed memory recall operations rather than direct metrics calls inside graph nodes.

#### Scenario: Hybrid recall completes
- **WHEN** a memory recall operation commits with strategy and result-count attributes
- **THEN** the Prometheus mirror SHALL observe its duration and retrieved count exactly once

### Requirement: ASR/TTS duration metrics
The system SHALL derive `anima_asr_duration_seconds` and `anima_tts_duration_seconds` from committed service operations, labeled with allowlisted provider identity.

#### Scenario: TTS degrades
- **WHEN** a TTS service operation commits with status `degraded`
- **THEN** its duration SHALL be observed and its degradation counter SHALL increment without being classified as a successful synthesis

### Requirement: WebSocket session and message metrics
The system SHALL derive active-session and accepted-message metrics from committed transport events. Filtered probes SHALL NOT increment accepted user-message totals.

#### Scenario: Inspection probe is filtered
- **WHEN** a marked inspection probe is dropped before orchestration
- **THEN** it SHALL NOT increment the accepted conversation message counter
