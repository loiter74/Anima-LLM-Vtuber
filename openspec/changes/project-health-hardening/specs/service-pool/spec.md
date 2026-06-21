## ADDED Requirements

### Requirement: Health probes do not destroy shared engines
Health checks, route smoke tests, and startup probes SHALL NOT call `ServiceContext.close()` on the ServicePool-owned shared context after shared LLM, TTS, or ASR engines have been initialized.

#### Scenario: Route smoke test constructs server
- **WHEN** a route smoke test constructs the ASGI server for lightweight route probing
- **THEN** it SHALL avoid calling service prewarm unless explicitly testing shared engine startup
- **AND** it SHALL NOT close ServicePool-owned shared engines as part of route cleanup

#### Scenario: ServicePool initialization fails
- **WHEN** ServicePool initialization raises before shared engines are published
- **THEN** cleanup MAY close partially initialized per-session resources
- **AND** the failure SHALL be reported without leaving `_ready` true

### Requirement: Startup probes distinguish lightweight and full readiness
The system SHALL distinguish lightweight route readiness probes from full Docker readiness verification.

#### Scenario: Lightweight route probe runs
- **WHEN** a developer runs the local route smoke checks
- **THEN** the checks SHALL validate route behavior without requiring GPU model downloads or remote provider calls

#### Scenario: Full Docker readiness runs
- **WHEN** final implementation verification runs after runtime code changes
- **THEN** the Docker startup protocol SHALL validate container health, `/health`, frontend HTTP 200, and logs
