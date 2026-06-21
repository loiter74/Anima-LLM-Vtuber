## ADDED Requirements

### Requirement: Required local health gates
The system SHALL provide a documented local health gate command that runs the repository's required backend, frontend, configuration, and runtime-smoke checks before a change is considered ready.

#### Scenario: Developer runs the health gate
- **WHEN** a developer runs the local health gate command from the repository root
- **THEN** the command SHALL execute backend lint, backend type check, backend tests, frontend type check, frontend tests, frontend build, Socket.IO event validation, Docker compose config validation, secret scanning, and health-critical route smoke checks
- **AND** the command SHALL exit non-zero when any required gate fails

#### Scenario: Health gate reports actionable failures
- **WHEN** one or more required gates fail
- **THEN** the health gate output SHALL identify the failing gate name and the underlying command or check that failed
- **AND** the output SHALL avoid printing secret values

### Requirement: CI enforces required gates
The CI workflows SHALL fail pull requests when required lint, type check, test, build, event validation, or route smoke gates fail.

#### Scenario: Backend lint fails in CI
- **WHEN** `ruff check src tests` reports an error in CI
- **THEN** the CI job SHALL fail
- **AND** it SHALL NOT hide the failure with `|| true` or equivalent pass-through behavior

#### Scenario: Deploy test fails
- **WHEN** the deploy workflow test stage fails
- **THEN** deployment SHALL NOT proceed unless the job is explicitly marked as an advisory non-release gate with a documented reason

### Requirement: Coverage baseline is explicit
The system SHALL enforce an explicit backend coverage threshold or an explicit ratcheting baseline with a target date to reach the documented 70% threshold.

#### Scenario: Coverage falls below configured threshold
- **WHEN** backend tests complete with coverage lower than the configured threshold
- **THEN** the health gate and CI SHALL fail

#### Scenario: Temporary coverage baseline is used
- **WHEN** the project temporarily uses a baseline below 70%
- **THEN** the baseline SHALL be documented with the current percentage, the target percentage, and follow-up tasks that close the gap

### Requirement: Dependency integrity checks
The system SHALL run dependency integrity checks for Python and frontend dependencies and classify all findings as fixed, required, or advisory with a documented owner.

#### Scenario: Python dependency conflict is detected
- **WHEN** `pip check` reports incompatible installed packages
- **THEN** the health gate SHALL fail unless the conflict is listed as a temporary advisory exception with an owner and expiration

#### Scenario: Frontend audit detects critical vulnerability
- **WHEN** `pnpm audit --registry=https://registry.npmjs.org` reports a critical vulnerability
- **THEN** the health gate SHALL fail unless the vulnerability is documented as a temporary advisory exception with mitigation and expiration

### Requirement: Plaintext secrets are forbidden in tracked config
Tracked configuration files SHALL NOT contain plaintext API keys, tokens, passwords, or bearer credentials.

#### Scenario: Secret-like value appears in tracked config
- **WHEN** the health gate scans tracked config files and finds a non-placeholder credential value
- **THEN** the gate SHALL fail and report the file and key name without printing the secret value

#### Scenario: Provider credential is required
- **WHEN** a provider requires an API key
- **THEN** tracked config SHALL reference an environment variable placeholder or documented secret source

### Requirement: Docker readiness validation is explicit
The system SHALL validate both Docker compose files syntactically and require full Docker startup verification after code changes that affect runtime behavior.

#### Scenario: Compose config is invalid
- **WHEN** `docker compose config -q` or `docker compose -f docker-compose.cpu.yml config -q` fails
- **THEN** the health gate SHALL fail

#### Scenario: Runtime code changes are complete
- **WHEN** implementation changes affect backend startup, frontend serving, health checks, Dockerfiles, or compose files
- **THEN** final verification SHALL include the project's Docker startup protocol with HTTP 200 `/health`, HTTP 200 frontend response, and log inspection for Traceback or ERROR entries
