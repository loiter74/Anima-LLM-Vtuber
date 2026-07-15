## MODIFIED Requirements

### Requirement: Health endpoint returns per-component status
The system SHALL preserve cheap `/health` process liveness and SHALL expose cached dependency and EffectiveConfig identity diagnostics through `/ready` and the component inspection snapshot. Provider network calls, model loading, and model generation SHALL NOT run inside the cheap liveness request.

#### Scenario: Process is alive but observation is degraded
- **WHEN** the ASGI process is serving but the ledger writer has failed
- **THEN** `/health` SHALL continue to prove process liveness
- **AND** `/ready` and the component diagnostic snapshot SHALL report observation degraded when observation is required by the active profile

#### Scenario: Process is alive but provider identity is invalid
- **WHEN** the server can answer HTTP but a selected provider is unready or resolved with the wrong identity
- **THEN** `/health` SHALL remain a cheap liveness response
- **AND** `/ready` SHALL return a non-ready status containing the sanitized component category and active EffectiveConfig version/hash

### Requirement: Health check covers core service dependencies
The system SHALL check the application-owned dependencies that serve real traffic: local observation ledger, ServicePool readiness/provider identity, active EffectiveConfig version/hashes, SharedMemoryRuntime health, its canonical SQLite store, derived-index backlog, Prometheus endpoint, and any profile-required remote model service. Health SHALL NOT open unrelated Chroma paths or treat an uninitialized required component as healthy.

#### Scenario: Observation ledger is writable
- **WHEN** the ledger writer is running, its queue is below threshold, and a probe transaction commits
- **THEN** `observation_ledger` SHALL report healthy with queue depth and last-commit age

#### Scenario: Memory index is degraded
- **WHEN** SharedMemoryRuntime reports a non-zero stuck outbox backlog or last indexing error
- **THEN** `memory_runtime` SHALL report degraded with the real backlog and sanitized reason

#### Scenario: Required ServicePool is not initialized
- **WHEN** the active runtime profile requires a real LLM, TTS, ASR, or VAD and ServicePool is not ready
- **THEN** the corresponding readiness check SHALL fail rather than return true as not configured

#### Scenario: Prometheus endpoint is reachable but inactive
- **WHEN** `/metrics` returns 200 but controlled ledger activity does not change the expected metric
- **THEN** `metrics_endpoint` SHALL report instrumentation degraded

#### Scenario: Required remote TTS identity matches
- **WHEN** `production` requires Qwen3 Alice and cached remote readiness reports the configured provider, model, and voice
- **THEN** the TTS component SHALL report healthy with sanitized configured/resolved identity
- **AND** it SHALL include the active EffectiveConfig version and hashes

#### Scenario: EffectiveConfig snapshot is stale or mismatched
- **WHEN** ServicePool, route handlers, or readiness cache reports a different profile, version, or hash from the active EffectiveConfig
- **THEN** readiness SHALL fail with a configuration-identity mismatch

## ADDED Requirements

### Requirement: Readiness is cached and identity-bearing
The `/ready` endpoint SHALL return a bounded, sanitized snapshot produced by startup/preflight and background component checks, including active profile, EffectiveConfig version/effective hash/semantic hash, and configured/resolved identities for required providers.

#### Scenario: All required components are ready
- **WHEN** configuration validation, ServicePool construction, required remote identity checks, and required local component checks have succeeded
- **THEN** `/ready` SHALL return HTTP 200 with `status: ok`
- **AND** every required provider SHALL show matching configured and resolved identities

#### Scenario: Required component is not ready
- **WHEN** any required component or identity check fails
- **THEN** `/ready` SHALL return a non-200 readiness status with a sanitized typed reason
- **AND** it SHALL not invoke a fallback provider or expose secrets
