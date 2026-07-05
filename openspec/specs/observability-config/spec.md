## Purpose
Defines the accepted behavior and requirements for the observability-config capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: OTLP export disabled by default
The observability configuration SHALL default to `otlp.enabled: false` so that OTLP gRPC export to the OTel Collector is opt-in, preventing continuous retry errors when the observability stack is not running.

#### Scenario: Default configuration
- **WHEN** `config/observability.yaml` is created from scratch or the `otlp.enabled` key is absent
- **THEN** the system SHALL treat OTLP export as disabled (no gRPC connection to port 4317)
- **THEN** local StatsStore SQLite tracing SHALL remain active

#### Scenario: Opt-in activation
- **WHEN** a user sets `otlp.enabled: true` AND starts the observability stack with `docker-compose -f observability/docker-compose.yml up -d`
- **THEN** OTLP gRPC export SHALL be active (traces → Tempo, metrics → Prometheus via OTel Collector)

### Requirement: Config comment documents opt-in behavior
The `config/observability.yaml` `otlp` section SHALL include a comment explaining that OTLP export requires the observability stack to be running.

#### Scenario: User reads config
- **WHEN** a user opens `config/observability.yaml`
- **THEN** the `otlp.enabled` field SHALL have an inline comment indicating that this requires `docker-compose -f observability/docker-compose.yml up -d`
