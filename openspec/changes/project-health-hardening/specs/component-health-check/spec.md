## ADDED Requirements

### Requirement: Health-critical route probes
The health check system SHALL include lightweight route probes for health-critical HTTP endpoints that can fail independently of `/health`.

#### Scenario: Singing recent route is probed
- **WHEN** the route probe checks `/api/singing/recent`
- **THEN** the probe SHALL complete without an unhandled exception
- **AND** it SHALL report success for an empty output directory as an HTTP 200 response with an empty JSON list

#### Scenario: Route raises an exception
- **WHEN** a health-critical route raises an unhandled exception during probing
- **THEN** the component health result SHALL report the route as failed with the exception type and sanitized message

### Requirement: Health response preserves readiness semantics
The health endpoint SHALL preserve its top-level readiness status while making route-level diagnostic failures visible.

#### Scenario: Route probe fails
- **WHEN** any required route probe fails
- **THEN** `GET /health` SHALL return a degraded status or include a failed route check that Docker/log verification can identify

#### Scenario: Existing status consumer reads health
- **WHEN** an existing consumer reads only the top-level `status` field
- **THEN** the value SHALL remain compatible with existing `"ok"` and `"degraded"` semantics
