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

The `/metrics` response SHALL include at least the following metric names expected by the inspection system: `anima_llm_errors_total` and `anima_node_duration_seconds`.

#### Scenario: Expected metrics present

- **WHEN** the inspection system calls `GET /metrics` and checks for expected metric names
- **THEN** both `anima_llm_errors_total` and `anima_node_duration_seconds` SHALL be present in the response body

### Requirement: Library dependency

The system SHALL use `prometheus_client` library to generate the Prometheus metrics endpoint. The `prometheus_client` package SHALL be added to `requirements.txt`.

#### Scenario: Dependency installed

- **WHEN** `pip list` is run
- **THEN** `prometheus-client` SHALL be listed as an installed package

### Requirement: Metrics are registered incrementally

The system SHALL NOT require all metrics to be pre-declared. Metrics SHALL be registered as they are first used. An empty `/metrics` response (containing only default Python process metrics) is acceptable on first startup.

#### Scenario: Metrics endpoint works before any custom metric is recorded

- **WHEN** the server starts and `GET /metrics` is called before any LLM error occurs
- **THEN** the response SHALL still return HTTP 200 and include default process metrics (e.g., `python_info`, `process_start_time_seconds`)
