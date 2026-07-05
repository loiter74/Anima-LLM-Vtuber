## Purpose
Defines the accepted behavior and requirements for the node-error-logging capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Graph nodes report structured errors to StatsStore
The system SHALL provide a shared `log_node_error()` utility that any graph node can call to record a provider failure with structured metadata (error type, provider name, duration) to StatsStore. The error SHALL be stored in the existing `spans` table with `status = "error"` and error metadata as JSON in the `attributes` column.

#### Scenario: LLM node logs timeout error
- **WHEN** `log_node_error("session-1", "llm_node", "timeout", "deepseek", 30000, trace_id)` is called
- **THEN** a new span is created in StatsStore with `node_name = "llm_node"` and `status = "error"`
- **AND** the span's `attributes` column contains `{"error_type": "timeout", "provider": "deepseek", "duration_ms": 30000}`

#### Scenario: TTS node logs rate-limit error
- **WHEN** `log_node_error("session-1", "tts_node", "rate_limit", "edge_tts", 5000, trace_id)` is called
- **THEN** a new span is created with `node_name = "tts_node"` and error metadata

#### Scenario: Node without trace_id logs error without span
- **WHEN** `log_node_error("session-1", "asr_node", "network_error", "whisper", 0, trace_id=None)` is called
- **THEN** no span is written to StatsStore
- **AND** a warning is logged via loguru

### Requirement: Error types are classified consistently
The system SHALL recognize four error types: `timeout` (provider call exceeded threshold), `rate_limit` (HTTP 429 or equivalent), `network_error` (connection/DNS/TLS failure), and `invalid_response` (unexpected format or empty response). Invalid or unknown error type strings SHALL default to `"unknown"`.

#### Scenario: Valid error type is accepted
- **WHEN** `log_node_error(..., error_type="timeout")` is called
- **THEN** error_type is stored as `"timeout"` without transformation

#### Scenario: Unknown error type defaults to "unknown"
- **WHEN** `log_node_error(..., error_type="cosmic_ray")` is called
- **THEN** error_type is stored as `"unknown"`
- **AND** a debug-level warning is logged

### Requirement: RAG retrieval is performed once per LLM turn
The `llm_node()` entry function SHALL perform RAG memory retrieval exactly once before dispatching to either the tool-calling or streaming path. The retrieved `memory_context` string SHALL be passed to both sub-functions as a parameter. Neither sub-function SHALL independently call `_retrieve_memory_context()`.

#### Scenario: Single RAG call for streaming path
- **WHEN** `llm_node()` is invoked with `enable_tools=False`
- **THEN** `_retrieve_memory_context()` is called exactly once
- **AND** the result is passed to `_llm_without_tools()` via parameter

#### Scenario: Single RAG call for tool-calling path
- **WHEN** `llm_node()` is invoked with `enable_tools=True` and valid `chat_model`
- **THEN** `_retrieve_memory_context()` is called exactly once
- **AND** the result is passed to `_llm_with_tools()` via parameter
