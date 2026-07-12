## MODIFIED Requirements

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

### Requirement: Health endpoint returns per-component status
The system SHALL preserve cheap `/health` liveness and SHALL expose component observation/readiness diagnostics through a non-blocking cached snapshot or inspection endpoint. Provider network calls and model generation SHALL NOT run inside the cheap liveness request.

#### Scenario: Process is alive but observation is degraded
- **WHEN** the ASGI process is serving but the ledger writer has failed
- **THEN** `/health` SHALL continue to prove process liveness
- **AND** the component diagnostic snapshot SHALL report observation degraded
