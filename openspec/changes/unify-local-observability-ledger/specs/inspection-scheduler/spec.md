## MODIFIED Requirements

### Requirement: Report persistence to StatsStore
The system SHALL persist each InspectionReport through the application-owned observation report store/query port. Inspection code SHALL NOT import StatsStore or access a private SQLite connection.

#### Scenario: Successful report persistence
- **WHEN** a scheduled inspection completes
- **THEN** its run identity, timestamps, overall result, and serialized checks SHALL commit to the local observation database

#### Scenario: Report persistence fails
- **WHEN** the observation ledger is unavailable
- **THEN** the in-memory report SHALL still be available for alerting
- **AND** the scheduler SHALL record a sanitized persistence failure without terminating

### Requirement: Scheduled daily execution
The system SHALL register one application-owned inspection task after startup readiness. The first run delay and interval SHALL be explicit configuration, and inspection SHALL use current runtime/query ports rather than constructing duplicate service or storage clients.

#### Scenario: First inspection runs
- **WHEN** the configured warmup completes
- **THEN** one full inspection SHALL run against the active server, ledger, ServicePool, and SharedMemoryRuntime instances

#### Scenario: One check crashes
- **WHEN** an inspection check raises unexpectedly
- **THEN** other checks SHALL continue and the scheduler SHALL remain alive for the next interval
