# Inspection Scheduler

## Purpose
Defines the accepted behavior and requirements for the inspection-scheduler capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

Orchestrates daily inspection runs: triggers all checks, aggregates results into structured reports, persists reports, and alerts on failures.
## Requirements
### Requirement: Data models for inspection results

The system SHALL define `CheckResult` and `InspectionReport` as Pydantic V2 `BaseModel` classes with `model_config = ConfigDict(frozen=True)`.

`CheckResult` SHALL have fields: `name` (str), `ok` (bool), `duration_ms` (float), `detail` (dict), `error` (str | None). It SHALL provide `passed()` and `failed()` class methods for construction.

`InspectionReport` SHALL have fields: `run_id` (str, UUID), `started_at` (float, timestamp), `finished_at` (float, timestamp), `checks` (dict[str, CheckResult]). It SHALL expose an `overall_ok` property that is `True` only when all checks pass.

#### Scenario: All checks pass

- **WHEN** `run_full_inspection()` completes with all 4 checks returning `ok: true`
- **THEN** the `InspectionReport.overall_ok` SHALL be `True`

#### Scenario: One check fails

- **WHEN** `run_full_inspection()` completes with `pipeline_smoke` returning `ok: false` and all other checks returning `ok: true`
- **THEN** the `InspectionReport.overall_ok` SHALL be `False`

### Requirement: Scheduled daily execution
The system SHALL register one application-owned inspection task after startup readiness. The first run delay and interval SHALL be explicit configuration, and inspection SHALL use current runtime/query ports rather than constructing duplicate service or storage clients.

#### Scenario: First inspection runs
- **WHEN** the configured warmup completes
- **THEN** one full inspection SHALL run against the active server, ledger, ServicePool, and SharedMemoryRuntime instances

#### Scenario: One check crashes
- **WHEN** an inspection check raises unexpectedly
- **THEN** other checks SHALL continue and the scheduler SHALL remain alive for the next interval

### Requirement: Report persistence to StatsStore
The system SHALL persist each InspectionReport through the application-owned observation report store/query port. Inspection code SHALL NOT import StatsStore or access a private SQLite connection.

#### Scenario: Successful report persistence
- **WHEN** a scheduled inspection completes
- **THEN** its run identity, timestamps, overall result, and serialized checks SHALL commit to the local observation database

#### Scenario: Report persistence fails
- **WHEN** the observation ledger is unavailable
- **THEN** the in-memory report SHALL still be available for alerting
- **AND** the scheduler SHALL record a sanitized persistence failure without terminating

### Requirement: Failure alerting via Notifier

The system SHALL send an alert through the existing Notifier system when `overall_ok` is `False`. The alert message SHALL include the `run_id`, timestamp, and a list of failed check names with their error strings.

Alerts SHALL use `severity="warning"`. Successful inspection runs SHALL NOT generate an alert.

#### Scenario: Inspection fails and alert is sent

- **WHEN** `overall_ok` is `False` and `store_report()` succeeds
- **THEN** the system SHALL call `notifier_manager.send()` with a message listing all failed checks and their errors

#### Scenario: Inspection passes without alert

- **WHEN** `overall_ok` is `True`
- **THEN** the system SHALL NOT send any alert

### Requirement: External API for manual inspection triggers

The system SHALL expose a function `async def run_full_inspection() -> InspectionReport` as the public entry point. This function SHALL be callable both by the scheduler and by external API endpoints for manual triggering.

#### Scenario: Manual inspection via API

- **WHEN** an API consumer calls `run_full_inspection()`
- **THEN** the function SHALL execute all registered checks, aggregate results into an `InspectionReport`, and return it — without persisting or alerting (caller controls side effects)
