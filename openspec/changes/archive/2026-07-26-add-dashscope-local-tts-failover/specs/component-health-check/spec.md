## ADDED Requirements

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
