## Purpose
Defines the accepted behavior and requirements for the otel-metrics capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
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

### Requirement: LLM request duration histogram
The system SHALL record an `anima_llm_request_duration_seconds` Histogram for every LLM API call, labeled with `provider` and `model`.

#### Scenario: LLM call duration recorded
- **WHEN** an LLM provider's chat/completion API call completes
- **THEN** `anima_llm_request_duration_seconds{provider="openai", model="gpt-4o-mini"}` SHALL observe the call duration

### Requirement: LLM token counters
The system SHALL record `anima_llm_tokens_total` Counter for input and output tokens, labeled with `provider`, `model`, and `type` (input/output).

#### Scenario: Token counts from API response
- **WHEN** OpenAI returns a chat completion with `response.usage.prompt_tokens=150` and `response.usage.completion_tokens=80`
- **THEN** `anima_llm_tokens_total{provider="openai", model="gpt-4o-mini", type="input"}` SHALL increment by 150
- **THEN** `anima_llm_tokens_total{provider="openai", model="gpt-4o-mini", type="output"}` SHALL increment by 80

#### Scenario: Token extraction from streaming
- **WHEN** an LLM call uses streaming mode where usage is only available on the final chunk
- **THEN** the system SHALL extract token counts from the final chunk and record them after the stream completes

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

### Requirement: Tool call metrics
The system SHALL record `anima_tool_calls_total` Counter and `anima_tool_duration_seconds` Histogram, labeled with `tool_name` and `status`.

#### Scenario: Tool execution counted
- **WHEN** tool_node executes a tool (e.g., web_search)
- **THEN** `anima_tool_calls_total{tool_name="web_search", status="success"}` SHALL increment by 1

#### Scenario: Tool error counted
- **WHEN** a tool execution raises an exception
- **THEN** `anima_tool_calls_total{tool_name="web_search", status="error"}` SHALL increment by 1
