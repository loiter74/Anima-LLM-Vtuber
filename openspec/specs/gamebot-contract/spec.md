## Purpose
Define the transport-independent command, response, event, and status contracts shared by Anima game-bot adapters and external runtimes.
## Requirements
### Requirement: Game bot commands use a stable contract
The system SHALL represent bot commands using a transport-independent request schema with an id, action, params, and timeout in milliseconds.

#### Scenario: Command request serializes for stdio transport
- **WHEN** Anima sends a game-bot command through the stdio transport
- **THEN** the serialized JSON line SHALL include `id`, `action`, `params`, and `timeout_ms`
- **THEN** the action and params SHALL match the validated command request

#### Scenario: Command timeout unit is stable
- **WHEN** a caller sends a command with a timeout in seconds through a compatibility adapter
- **THEN** the command contract SHALL expose the timeout to the runtime in milliseconds

### Requirement: Game bot responses use a stable contract
The system SHALL represent bot command results using a response schema with id, status, and result fields.

#### Scenario: Response resolves matching command
- **WHEN** the transport receives a response whose id matches a pending command
- **THEN** the pending command SHALL resolve with the response status and result

#### Scenario: Error response is preserved
- **WHEN** the runtime returns a response with status `error`
- **THEN** Anima SHALL preserve the error result without converting it to an unrelated exception shape

### Requirement: Game bot events use a stable contract
The system SHALL represent asynchronous runtime notifications as events with a type and payload.

#### Scenario: Known event validates
- **WHEN** the runtime emits a known event such as `login`, `spawn`, `heartbeat`, `initial_loadout`, or `client_viewer_status`
- **THEN** Anima SHALL validate and relay the event without requiring a command id

#### Scenario: Unknown event remains non-fatal
- **WHEN** the runtime emits an unknown event type
- **THEN** Anima SHALL preserve the event type and payload as metadata
- **THEN** the event SHALL NOT crash the bridge reader

### Requirement: Game bot status snapshots are generic with metadata
The system SHALL represent status snapshots using generic fields for position, health, food, dimension, inventory, held item, nearby entities, and metadata.

#### Scenario: Minecraft HUD data fits the generic status
- **WHEN** the Minecraft runtime returns status data for the existing frontend HUD
- **THEN** the generic status snapshot SHALL include the fields required by the HUD
- **THEN** Minecraft-specific details SHALL be carried in metadata when no generic field exists

### Requirement: Versioned capability manifest
Every game-bot runtime SHALL expose a structured manifest containing protocol version, runtime identity, capability names, risk classifications, and parameter schemas.

#### Scenario: Controller connects to runtime
- **WHEN** the game-bot client establishes a connection
- **THEN** it SHALL retrieve and validate the capability manifest before allowing production actions

### Requirement: Structured observation contract
The game-bot contract SHALL expose observations with correlation metadata, position, health, food, inventory, equipment, environment context, and runtime identity without using administrator state mutation.

#### Scenario: Learning requests world state
- **WHEN** a learning session calls `observe`
- **THEN** the runtime SHALL return a schema-valid observation attributable to the connected bot and runtime instance

### Requirement: Structured action receipts
Every executed action SHALL return a structured receipt with session, task, correlation, capability, normalized parameters, timing, outcome, structured error, runtime identity, and before/after observation references.

#### Scenario: Action succeeds
- **WHEN** a survival-safe action completes
- **THEN** its receipt SHALL contain enough information to attribute resulting inventory and state changes to that action

#### Scenario: Action fails
- **WHEN** an action times out or fails
- **THEN** its receipt SHALL contain a machine-readable error code and MUST NOT rely on natural-language parsing for recovery decisions

#### Scenario: Generated skill invokes multiple capabilities
- **WHEN** `eval_skill` invokes more than one authorized safe wrapper
- **THEN** the runtime SHALL return a `SkillExecutionResult` containing every wrapper ActionReceipt in execution order as one verifiable chain

### Requirement: Action cancellation
The game-bot contract SHALL allow the controller to cancel the active action and obtain a fresh observation after cleanup.

#### Scenario: Controller cancels timed-out action
- **WHEN** the controller invokes cancellation
- **THEN** the runtime SHALL stop pathfinding, combat, digging, and other active action resources before acknowledging cancellation
