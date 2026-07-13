# prometheus-metrics-endpoint Specification

## Purpose
TBD - created by archiving change fix-startup-bugs-parallel. Update Purpose after archive.
## Requirements
### Requirement: `/metrics` returns HTTP 200 with Prometheus text format

The server SHALL expose a `GET /metrics` endpoint that returns HTTP 200 with `Content-Type: text/plain; charset=utf-8` containing Prometheus-format metrics. The endpoint SHALL be mounted on the same ASGI server (port 12394) as the main application.

#### Scenario: Metrics endpoint returns valid response

- **WHEN** `GET /metrics` is called on the main server port
- **THEN** the response SHALL have status 200 and body SHALL contain at least `anima_` and `process_` metric prefixes

#### Scenario: Metrics endpoint is always available

- **WHEN** the server is running in any mode (dev, production, with or without OpenTelemetry)
- **THEN** `GET /metrics` SHALL always return HTTP 200 (not 404)

### Requirement: Core metric counters exist
The `/metrics` response SHALL include the core Animetta metric families after their mirror is initialized, and those metric values SHALL be driven by committed observation records.

#### Scenario: Controlled node operation commits
- **WHEN** inspection commits one controlled workflow operation
- **THEN** the corresponding `anima_node_duration_seconds_count` value SHALL increase by exactly one

#### Scenario: Metric name exists without activity
- **WHEN** a core metric family is registered but a controlled record does not change its value
- **THEN** metrics inspection SHALL report failure rather than treating name presence as proof of instrumentation

### Requirement: Library dependency

The system SHALL use `prometheus_client` library to generate the Prometheus metrics endpoint. The `prometheus_client` package SHALL be added to `requirements.txt`.

#### Scenario: Dependency installed

- **WHEN** `pip list` is run
- **THEN** `prometheus-client` SHALL be listed as an installed package

### Requirement: Metrics are registered incrementally
Metrics SHALL be registered by the Prometheus mirror using bounded names and label sets. `/metrics` SHALL remain available before custom observations, but health validation of business instrumentation SHALL require a controlled delta.

#### Scenario: Server has no conversations yet
- **WHEN** `/metrics` is called before custom observations
- **THEN** it SHALL return HTTP 200 with process metrics
- **AND** it SHALL NOT claim that conversation instrumentation has been exercised
