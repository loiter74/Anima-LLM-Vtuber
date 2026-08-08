## Purpose
Define the transport-independent command, response, event, and status contracts shared by Anima game-bot adapters and external runtimes.
## Requirements
### Requirement: Game bot commands use a stable contract
The v2 system SHALL represent each runtime step with a transport-independent request containing transport ID, command ID, step ID, correlation ID, bound runtime instance ID, capability, canonical parameters, remaining budget, and deadline.

#### Scenario: Command request serializes for stdio transport
- **WHEN** Anima sends a v2 game-bot step through stdio
- **THEN** the serialized JSON line SHALL validate against the canonical request schema
- **THEN** all execution identity and budget fields SHALL match the controller-approved step

#### Scenario: Command timeout unit is stable
- **WHEN** Python serializes a v2 deadline or compatibility timeout
- **THEN** the contract SHALL use its declared unit and SHALL NOT ambiguously mix seconds and milliseconds

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
Every production runtime SHALL expose a v2 manifest containing protocol and runtime-instance identity, Minecraft and stable environment profile fields, capability risk and parameter schemas, receipt schema versions, and explicit support flags for single-flight, correlation idempotency, cooperative cancellation, per-action budget enforcement, and receipt chains.

#### Scenario: Controller connects to runtime
- **WHEN** the game-bot client establishes a connection
- **THEN** it SHALL retrieve and validate the v2 manifest before readiness
- **THEN** missing required guarantees SHALL reject production execution

### Requirement: Structured observation contract
The v2 observation SHALL contain correlation metadata, capture time/tick, content hash, runtime-instance identity, stable environment profile, position, health, food, inventory, equipment, and environment state without administrator mutation.

#### Scenario: Executor requests fresh world state
- **WHEN** the command executor requests an observation after an action
- **THEN** the runtime SHALL return a schema-valid observation attributable to the bound runtime instance
- **THEN** its capture marker SHALL allow the controller to prove whether it follows the relevant receipt

### Requirement: Structured action receipts
Every executed v2 capability SHALL return an ordered, hash-linked receipt containing command, step, correlation, capability, canonical parameter hash, action sequence, timing/ticks, outcome, structured error, runtime-instance identity, before/after observation references, explained mutations, and budget usage.

#### Scenario: Action succeeds
- **WHEN** a survival-safe action completes
- **THEN** its receipt SHALL contain enough attributable evidence to verify goal predicates and charge budget

#### Scenario: Action fails
- **WHEN** an action times out, fails, or has unknown outcome
- **THEN** its receipt or structured transport error SHALL use a machine-readable code and explicit outcome-known/world-may-have-changed fields

#### Scenario: Skill IR executes multiple steps
- **WHEN** the controller interprets a Skill IR program containing multiple action steps
- **THEN** each runtime call SHALL return its own receipt linked to the same parent command in execution order
- **THEN** the runtime SHALL NOT execute the complete Skill IR as arbitrary code

### Requirement: Action cancellation
The v2 contract SHALL allow idempotent cooperative cancellation of the active correlation, and a cancellation acknowledgment SHALL mean only that the runtime accepted the signal rather than that all effects safely stopped.

#### Scenario: Controller cancels active action
- **WHEN** the controller invokes cancellation
- **THEN** the runtime SHALL signal pathfinding, combat, digging, and other active resources to stop
- **THEN** the controller SHALL require a final receipt, idle health, and a fresh observation before declaring cancellation reconciled

### Requirement: Runtime correlation is idempotent within an instance
The v2 runtime SHALL maintain an instance-scoped correlation ledger so a repeated correlation with identical canonical content does not execute twice.

#### Scenario: Identical correlation is retried in the same runtime instance
- **WHEN** the runtime receives the same correlation ID and canonical request hash again
- **THEN** it SHALL return the recorded current or final result without repeating the action

#### Scenario: Correlation content conflicts
- **WHEN** the runtime receives an existing correlation ID with different canonical content
- **THEN** it SHALL return `CORRELATION_CONFLICT` without executing

### Requirement: Runtime correlation state is inspectable without execution
The v2 runtime SHALL allow Python to inspect an existing correlation as `not_found`, `accepted`, `running`, or `terminal` without starting or retrying an action, and a terminal inspection SHALL return the original receipt.

#### Scenario: Action response is lost after completion
- **WHEN** Python loses the execute response and inspects the same correlation in the same runtime instance
- **THEN** the runtime SHALL return its recorded terminal receipt without executing the capability again

#### Scenario: Correlation is absent in the same retained instance
- **WHEN** inspection returns `not_found` while the same runtime instance and ledger-retention guarantee remain valid
- **THEN** recovery MAY conclude that the runtime never accepted that correlation

#### Scenario: Runtime instance changed
- **WHEN** Python inspects using a correlation bound to a previous runtime instance
- **THEN** the runtime SHALL return an instance mismatch rather than treating a new-instance absence as proof of no effect

### Requirement: Runtime enforces single-flight and action budgets
The v2 runtime SHALL reject concurrent state-changing actions and SHALL enforce the controller-provided remaining action budget inside Mineflayer capability wrappers.

#### Scenario: Concurrent action bypass is attempted
- **WHEN** a second state-changing request arrives while one is active
- **THEN** the runtime SHALL reject it without starting another world mutation

#### Scenario: Capability reaches budget
- **WHEN** an active wrapper reaches its remaining distance, damage, block-change, resource, or time limit
- **THEN** it SHALL stop further action and return attributable budget usage and outcome

