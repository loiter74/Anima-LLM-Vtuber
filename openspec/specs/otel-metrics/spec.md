## Purpose
Defines the accepted behavior and requirements for the otel-metrics capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: OTel MeterProvider initialized
The system SHALL initialize an OpenTelemetry MeterProvider alongside the existing TracerProvider during `init_tracing()`. Metrics SHALL be exported to the OTel Collector via OTLP only when `otlp.enabled` is explicitly set to `true` in `config/observability.yaml`.

#### Scenario: MeterProvider created at startup (OTLP disabled — default)
- **WHEN** the backend starts and `init_tracing()` is called with `otlp.enabled: false` (the default)
- **THEN** a MeterProvider SHALL be created with the same `service.name` resource attribute as the TracerProvider
- **THEN** NO PeriodicExportingMetricReader SHALL be configured (no OTLP gRPC connection attempted)
- **THEN** metric instruments SHALL still be defined and usable for local consumption (e.g., via `http://localhost:8889` when Collector is running)

#### Scenario: MeterProvider created at startup (OTLP enabled — opt-in)
- **WHEN** the backend starts and `init_tracing()` is called with `otlp.enabled: true`
- **THEN** a PeriodicExportingMetricReader SHALL be configured with an OTLP gRPC metric exporter pointing to the configured endpoint (default: `http://localhost:4317`)

#### Scenario: Metrics disabled when tracing disabled
- **WHEN** `config/observability.yaml` has `tracing.enabled: false`
- **THEN** no MeterProvider SHALL be created (no metrics overhead)

### Requirement: LangGraph node duration histogram
The system SHALL record an `anima_node_duration_seconds` Histogram for every LangGraph node execution, labeled with `node_name`.

#### Scenario: Node duration recorded on completion
- **WHEN** a LangGraph node (e.g., "llm", "asr", "tts") completes execution
- **THEN** `anima_node_duration_seconds{node_name="llm"}` SHALL observe the node's wall-clock duration in seconds
- **THEN** the histogram SHALL have buckets: [0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60]

#### Scenario: All 7 nodes tracked
- **WHEN** a full pipeline runs (asr → personality → llm → tts → emotion → output, optionally tool)
- **THEN** each of the 7+ nodes SHALL produce a histogram observation

### Requirement: LangGraph node error counter
The system SHALL record an `anima_node_errors_total` Counter for every node execution failure, labeled with `node_name` and `error_type`.

#### Scenario: Node error counted
- **WHEN** a LangGraph node raises an exception
- **THEN** `anima_node_errors_total{node_name="llm", error_type="timeout"}` SHALL increment by 1

#### Scenario: Error types include structured categories
- **WHEN** an error occurs with a known error_type (timeout, rate_limit, network_error, invalid_response)
- **THEN** the `error_type` label SHALL reflect the structured error category

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
The system SHALL record RAG retrieval performance metrics: `anima_rag_retrieval_duration_seconds` Histogram and `anima_rag_chunks_retrieved` Histogram, labeled with `strategy`.

#### Scenario: Hybrid search retrieval measured
- **WHEN** MemoryMiddleware.before_llm_call() performs RAG retrieval
- **THEN** `anima_rag_retrieval_duration_seconds{strategy="hybrid"}` SHALL observe the retrieval duration
- **THEN** `anima_rag_chunks_retrieved{strategy="hybrid"}` SHALL observe the number of retrieved chunks

### Requirement: ASR/TTS duration metrics
The system SHALL record `anima_asr_duration_seconds` and `anima_tts_duration_seconds` Histograms, labeled with `provider`.

#### Scenario: TTS synthesis duration measured
- **WHEN** tts_node calls tts_engine.synthesize()
- **THEN** `anima_tts_duration_seconds{provider="edge_tts"}` SHALL observe the synthesis duration

### Requirement: WebSocket session and message metrics
The system SHALL record `anima_active_sessions` Gauge and `anima_session_messages_total` Counter.

#### Scenario: Active session tracking
- **WHEN** a client connects via Socket.IO
- **THEN** `anima_active_sessions` SHALL increment by 1
- **WHEN** a client disconnects
- **THEN** `anima_active_sessions` SHALL decrement by 1

#### Scenario: Message counting
- **WHEN** a user sends a text or audio message
- **THEN** `anima_session_messages_total` SHALL increment by 1

### Requirement: Tool call metrics
The system SHALL record `anima_tool_calls_total` Counter and `anima_tool_duration_seconds` Histogram, labeled with `tool_name` and `status`.

#### Scenario: Tool execution counted
- **WHEN** tool_node executes a tool (e.g., web_search)
- **THEN** `anima_tool_calls_total{tool_name="web_search", status="success"}` SHALL increment by 1

#### Scenario: Tool error counted
- **WHEN** a tool execution raises an exception
- **THEN** `anima_tool_calls_total{tool_name="web_search", status="error"}` SHALL increment by 1
