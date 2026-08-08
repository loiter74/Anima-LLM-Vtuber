# Component Health Check
## Purpose
Defines the accepted behavior and requirements for the component-health-check capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

Provides granular per-component health status for the Anima backend, replacing the binary `/health` endpoint (`{"status":"ok"}`) with component-level diagnostics.
## Requirements
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

### Requirement: Component checks execute concurrently with independent timeouts

The system SHALL execute all component health probes concurrently using `asyncio.gather(return_exceptions=True)`. Each component probe SHALL have its own timeout via `asyncio.wait_for()`. A timeout or exception in one probe SHALL NOT prevent other probes from completing.

#### Scenario: Slow component does not block others

- **WHEN** the LLM probe is configured with a 5-second timeout and takes 6 seconds to respond
- **THEN** the LLM check SHALL report `"ok": false` with an `"error"` field indicating timeout, and all other component checks (TTS, ASR, Chroma, etc.) SHALL complete and report their status within their respective timeouts

#### Scenario: Component raises an exception

- **WHEN** the Chroma probe raises a `ConnectionError`
- **THEN** the Chroma check SHALL report `"ok": false` with `"error": "ConnectionError: <message>"`, and other component checks SHALL be unaffected

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

### Requirement: Composite TTS readiness is degradation-aware
The cached runtime readiness snapshot SHALL treat TTS as ready when either configured child backend has valid identity and is ready, SHALL mark a single-backend state degraded, and SHALL fail when neither backend is usable.

#### Scenario: Only local TTS is available
- **WHEN** the primary is unavailable and the local child has valid cached readiness
- **THEN** `/ready` SHALL return HTTP 200
- **AND** TTS SHALL report `ready=true`, `degraded=true`, and the local active backend

#### Scenario: Only primary TTS is available
- **WHEN** local Qwen is unavailable and DashScope has valid cached readiness
- **THEN** `/ready` SHALL return HTTP 200 with TTS marked degraded

#### Scenario: No TTS backend is available
- **WHEN** both child backends are unavailable or invalid
- **THEN** `/ready` SHALL return HTTP 503 with sanitized child failure categories

### Requirement: Readiness performs no provider I/O
The `/ready` request SHALL only read bounded cached state and SHALL NOT connect to DashScope, call the host service, or generate speech.

#### Scenario: Readiness is requested during an outage
- **WHEN** `/ready` is called while both networks are unreachable
- **THEN** it SHALL return from cached state without attempting network I/O

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

