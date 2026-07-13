# voyager-control-plane Specification

## Purpose
TBD - created by archiving change harden-voyager-controller. Update Purpose after archive.
## Requirements
### Requirement: Single Voyager mode authority
The system SHALL maintain Voyager mode, session lifecycle, and active task ownership in one Python `VoyagerController`, and the external runtime MUST NOT independently own Voyager business mode.

#### Scenario: Start learning from public tool
- **WHEN** `mc_voyager_learn` is invoked while the game bot is connected
- **THEN** the controller SHALL transition to `learn` and start exactly one learning session

#### Scenario: Concurrent transition
- **WHEN** two callers request different Voyager modes concurrently
- **THEN** the controller SHALL serialize the transitions and leave exactly one active session

### Requirement: Controller public operations
The controller SHALL expose asynchronous operations to start learning, start live mode, run a live goal, start fallback, stop, and return structured status.

#### Scenario: Live goal invocation
- **WHEN** a caller submits a goal in live mode
- **THEN** the controller SHALL select and execute a trusted skill or return a structured fallback outcome

### Requirement: Recoverable task lifecycle
The controller SHALL checkpoint only committed task boundaries and MUST NOT award progress from an interrupted task.

#### Scenario: Runtime exits during an action
- **WHEN** the runtime disconnects before an action receipt chain is committed
- **THEN** the controller SHALL invalidate the partial task, restore the last committed checkpoint, and obtain a fresh observation before continuing

#### Scenario: Unexplained inventory after recovery
- **WHEN** the fresh observation contains inventory changes not explained by committed receipts
- **THEN** the controller SHALL quarantine the session and SHALL NOT use those items for technology unlocks

### Requirement: Safe fallback isolation
Fallback actions SHALL preserve bot safety without satisfying evidence requirements for a failed learning or live task.

#### Scenario: Learning task falls back after danger
- **WHEN** a learning task is interrupted by a survival fallback
- **THEN** fallback receipts SHALL be tagged separately and SHALL NOT validate or unlock the interrupted task
