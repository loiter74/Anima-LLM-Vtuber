# Component Health Check

## Purpose
Defines the accepted behavior and requirements for the component-health-check capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

Provides granular per-component health status for the Anima backend, replacing the binary `/health` endpoint (`{"status":"ok"}`) with component-level diagnostics.

## Requirements

### Requirement: Health endpoint returns per-component status

The system SHALL return a `"status"` field of either `"ok"` (all components healthy) or `"degraded"` (at least one component unhealthy) in the `GET /health` response, plus a `"checks"` object containing per-component `CheckResult` entries.

#### Scenario: All components healthy

- **WHEN** the server is running and all registered components respond within their timeouts
- **THEN** `GET /health` returns `{"status": "ok", "checks": {"llm_available": {"ok": true, ...}, "tts_available": {"ok": true, ...}, ...}}`

#### Scenario: One component fails

- **WHEN** the LLM component times out but all other components respond normally
- **THEN** `GET /health` returns `{"status": "degraded", "checks": {"llm_available": {"ok": false, "error": "timeout"}, "tts_available": {"ok": true, ...}, ...}}`

### Requirement: Component checks execute concurrently with independent timeouts

The system SHALL execute all component health probes concurrently using `asyncio.gather(return_exceptions=True)`. Each component probe SHALL have its own timeout via `asyncio.wait_for()`. A timeout or exception in one probe SHALL NOT prevent other probes from completing.

#### Scenario: Slow component does not block others

- **WHEN** the LLM probe is configured with a 5-second timeout and takes 6 seconds to respond
- **THEN** the LLM check SHALL report `"ok": false` with an `"error"` field indicating timeout, and all other component checks (TTS, ASR, Chroma, etc.) SHALL complete and report their status within their respective timeouts

#### Scenario: Component raises an exception

- **WHEN** the Chroma probe raises a `ConnectionError`
- **THEN** the Chroma check SHALL report `"ok": false` with `"error": "ConnectionError: <message>"`, and other component checks SHALL be unaffected

### Requirement: Health check covers core service dependencies

The system SHALL check the following components by default:

| Component ID | What It Checks |
|--------------|----------------|
| `stats_store` | StatsStore SQLite connectivity (single-row query) |
| `chroma` | ChromaDB collection accessibility |
| `llm_available` | LLM service model loaded and responsive |
| `tts_available` | TTS engine initialized and responsive |
| `asr_available` | ASR model loaded and responsive |
| `memory_read` | Memory system readable (hybrid search probe) |
| `metrics_endpoint` | Prometheus `/metrics` endpoint returns 200 and contains expected gauge/counter names |

#### Scenario: StatsStore SQLite is locked

- **WHEN** the StatsStore SQLite database is locked by another process
- **THEN** the `stats_store` check SHALL report `"ok": false` with `"error"` indicating the lock failure

#### Scenario: Metrics endpoint missing expected metrics

- **WHEN** `GET /metrics` returns HTTP 200 but does not contain `anima_llm_errors_total`
- **THEN** the `metrics_endpoint` check SHALL report `"ok": false` with `"error": "missing_core_metric: anima_llm_errors_total"`

### Requirement: Backward compatibility of health endpoint

The system SHALL preserve the existing `"service"`, `"timestamp"`, and `"status"` fields in the `/health` response. The new `"checks"` field SHALL be additive. Existing consumers that only read `"status"` SHALL continue to work — `"status": "ok"` maps to the pre-existing behavior.

#### Scenario: Existing consumer reads only status field

- **WHEN** a monitoring tool reads `response["status"]` from the enhanced `/health` response
- **THEN** it SHALL receive `"ok"` when all components are healthy, and `"degraded"` when any component is unhealthy

### Requirement: Component check timeout configuration

The system SHALL define per-component timeout values (in seconds). These SHALL be defined as constants in the check definition, not hardcoded in the execution logic.

#### Scenario: Changing timeout for a component

- **WHEN** a developer changes the `timeout` field in a `ComponentCheck` definition
- **THEN** the next health check invocation SHALL use the new timeout without modifying any execution logic
