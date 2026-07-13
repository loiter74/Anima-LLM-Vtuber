## Purpose
Defines the accepted behavior and requirements for the observability-config capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: OTLP export disabled by default
The observability configuration SHALL default to `otlp.enabled: false` so OTLP export is opt-in. The local observation ledger SHALL default to enabled and SHALL remain the authoritative trace store regardless of OTLP availability.

#### Scenario: Default configuration
- **WHEN** `config/observability.yaml` is created from scratch or the `otlp.enabled` key is absent
- **THEN** the system SHALL make no OTLP connection
- **AND** the local SQLite observation ledger SHALL record complete traces, operations, and events

#### Scenario: Opt-in activation
- **WHEN** a user sets `otlp.enabled: true` and starts the observability stack
- **THEN** committed ledger records SHALL be mirrored through OTLP
- **AND** OTLP SHALL NOT write records back into the local ledger

### Requirement: Config comment documents opt-in behavior
The `config/observability.yaml` `otlp` section SHALL include a comment explaining that OTLP export requires the observability stack to be running.

#### Scenario: User reads config
- **WHEN** a user opens `config/observability.yaml`
- **THEN** the `otlp.enabled` field SHALL have an inline comment indicating that this requires `docker-compose -f observability/docker-compose.yml up -d`

### Requirement: Local ledger configuration is explicit
The observability configuration SHALL define local ledger enablement, database path, queue capacity, shutdown drain timeout, and profile-aware privacy defaults.

#### Scenario: Configuration is absent
- **WHEN** the local ledger section is absent
- **THEN** the system SHALL enable the ledger at `data/observations.db` with development full-content mode and golden/production redacted mode

#### Scenario: Local observation is disabled
- **WHEN** an operator explicitly disables the local ledger
- **THEN** the system SHALL install a NoOp recorder
- **AND** health SHALL report observation as disabled rather than healthy
