## ADDED Requirements

### Requirement: Event validation is a release gate
The Socket.IO event registry validation SHALL run as a required gate in Docker builds and CI health checks.

#### Scenario: Event validation fails
- **WHEN** `scripts/validate-events.py` reports a missing TypeScript reference, invalid event name, or Python emit mismatch
- **THEN** Docker build and CI health gates SHALL fail

#### Scenario: Event validation passes
- **WHEN** all events in `config/socket-events.json` are referenced by the TypeScript constants file and all literal backend emits are registered
- **THEN** the event validation gate SHALL pass

### Requirement: New events use the shared registry
New frontend and backend Socket.IO events SHALL be added through `config/socket-events.json` and consumed through generated or centralized constants.

#### Scenario: Backend adds a literal emit
- **WHEN** backend code adds a new literal `sio.emit()` event name
- **THEN** that event name SHALL exist in `config/socket-events.json`

#### Scenario: Frontend adds an event listener
- **WHEN** frontend code adds a new Socket.IO listener or emitter
- **THEN** it SHALL use `Events.*` constants rather than an unregistered string literal
