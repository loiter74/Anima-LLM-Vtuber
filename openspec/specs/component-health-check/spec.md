# Component Health Check

## Purpose
Defines the accepted behavior and requirements for the component-health-check capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

Provides granular per-component health status for the Anima backend, replacing the binary `/health` endpoint (`{"status":"ok"}`) with component-level diagnostics.
## Requirements
### Requirement: Health endpoint returns per-component status
The system SHALL preserve cheap `/health` liveness and SHALL expose component observation/readiness diagnostics through a non-blocking cached snapshot or inspection endpoint. Provider network calls and model generation SHALL NOT run inside the cheap liveness request.

#### Scenario: Process is alive but observation is degraded
- **WHEN** the ASGI process is serving but the ledger writer has failed
- **THEN** `/health` SHALL continue to prove process liveness
- **AND** the component diagnostic snapshot SHALL report observation degraded

### Requirement: Component checks execute concurrently with independent timeouts

The system SHALL execute all component health probes concurrently using `asyncio.gather(return_exceptions=True)`. Each component probe SHALL have its own timeout via `asyncio.wait_for()`. A timeout or exception in one probe SHALL NOT prevent other probes from completing.

#### Scenario: Slow component does not block others

- **WHEN** the LLM probe is configured with a 5-second timeout and takes 6 seconds to respond
- **THEN** the LLM check SHALL report `"ok": false` with an `"error"` field indicating timeout, and all other component checks (TTS, ASR, Chroma, etc.) SHALL complete and report their status within their respective timeouts

#### Scenario: Component raises an exception

- **WHEN** the Chroma probe raises a `ConnectionError`
- **THEN** the Chroma check SHALL report `"ok": false` with `"error": "ConnectionError: <message>"`, and other component checks SHALL be unaffected

### Requirement: Health check covers core service dependencies
The system SHALL check the application-owned dependencies that serve real traffic: local observation ledger, ServicePool readiness/provider identity, SharedMemoryRuntime health, its canonical SQLite store, derived-index backlog, and the Prometheus endpoint. Health SHALL NOT open unrelated Chroma paths or treat an uninitialized required component as healthy.

#### Scenario: Observation ledger is writable
- **WHEN** the ledger writer is running, its queue is below threshold, and a probe transaction commits
- **THEN** `observation_ledger` SHALL report healthy with queue depth and last-commit age

#### Scenario: Memory index is degraded
- **WHEN** SharedMemoryRuntime reports a non-zero stuck outbox backlog or last indexing error
- **THEN** `memory_runtime` SHALL report degraded with the real backlog and sanitized reason

#### Scenario: Required ServicePool is not initialized
- **WHEN** the active runtime profile requires a real LLM or TTS and ServicePool is not ready
- **THEN** the corresponding health check SHALL fail rather than return true as not configured

#### Scenario: Prometheus endpoint is reachable but inactive
- **WHEN** `/metrics` returns 200 but controlled ledger activity does not change the expected metric
- **THEN** `metrics_endpoint` SHALL report instrumentation degraded

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
