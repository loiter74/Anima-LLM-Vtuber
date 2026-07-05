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

The system SHALL register an `asyncio.Task` during server startup (`socketio_server.py`) that runs a full inspection once every 24 hours. The first inspection SHALL be delayed by 10 seconds after task creation to allow service warmup.

The scheduler loop SHALL be wrapped in `try/except Exception` — a single inspection failure SHALL NOT terminate the scheduler task.

#### Scenario: Server starts and runs first inspection after warmup

- **WHEN** the server process starts and the scheduler task is created
- **THEN** the scheduler SHALL wait 10 seconds, then execute `run_full_inspection()`, then wait 24 hours before the next execution

#### Scenario: Inspection crashes due to transient error

- **WHEN** `run_full_inspection()` raises an unhandled `Exception`
- **THEN** the scheduler SHALL log the error via `logger.error()` and SHALL NOT terminate (next inspection runs in 24 hours as scheduled)

### Requirement: Report persistence to StatsStore

The system SHALL persist each `InspectionReport` to the existing StatsStore SQLite database using a new `inspection_reports` table. The report SHALL be queryable via StatsStore API for trend analysis and dashboard display.

#### Scenario: Successful report persistence

- **WHEN** an inspection completes and produces a report
- **THEN** the report SHALL be stored with `run_id`, `started_at`, `finished_at`, `overall_ok`, and serialized `checks` JSON

#### Scenario: StatsStore unavailable during persistence

- **WHEN** `store_report()` fails because StatsStore SQLite is unreachable
- **THEN** the error SHALL be logged but SHALL NOT prevent the alert from being sent (alert uses in-memory report data)

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
