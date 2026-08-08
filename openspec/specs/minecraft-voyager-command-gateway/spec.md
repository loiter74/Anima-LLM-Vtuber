# minecraft-voyager-command-gateway Specification

## Purpose
TBD - created by archiving change unify-minecraft-voyager-control-plane. Update Purpose after archive.
## Requirements
### Requirement: Minecraft exposes exactly three Voyager tools
The system SHALL expose `mc_execute`, `mc_status`, and `mc_stop` as the complete public LangChain Minecraft tool surface, and no public tool SHALL invoke `MinecraftBridge.send_command` directly.

#### Scenario: Tools register after runtime startup
- **WHEN** the Minecraft runtime and Voyager control plane become ready
- **THEN** the registry SHALL contain exactly `mc_execute`, `mc_status`, and `mc_stop` for Minecraft control
- **THEN** the registry SHALL NOT contain the removed fine-grained gameplay or mode tools

### Requirement: Execute requests use typed goals, actions, budgets, and persistent identity
`mc_execute` SHALL require an injected caller scope, a persistent request ID, caller-selected `learn`, `live`, `fallback`, or `atomic` mode, exactly one mode-valid structured goal or action, and an effective budget that cannot exceed configured limits.

#### Scenario: Goal mode receives natural-language string
- **WHEN** learn, live, or fallback mode receives an unstructured goal string instead of a valid `GoalSpec`
- **THEN** the gateway SHALL reject the request before enqueueing

#### Scenario: Atomic action validates against manifest
- **WHEN** atomic mode receives an action
- **THEN** the gateway SHALL validate its capability and normalized parameters against the connected manifest
- **THEN** it SHALL reject unknown capability, invalid parameters, or a simultaneous goal

#### Scenario: Caller requests excessive budget
- **WHEN** a caller requests a limit above the configured mode maximum
- **THEN** the gateway SHALL use the configured maximum as the effective budget and return both requested and effective values

### Requirement: Execute submission is durably asynchronous
`mc_execute` SHALL durably accept a valid command before returning and SHALL separate optional bounded tool waiting from command queue and execution lifecycles.

#### Scenario: Default submission
- **WHEN** a caller submits a valid command with zero wait seconds
- **THEN** the tool SHALL return its command ID, request ID, queue sequence, state, and projection version without waiting for terminal execution

#### Scenario: Tool wait expires
- **WHEN** the optional tool wait expires while the command is queued or running
- **THEN** the command SHALL remain governed by its queue and execution budgets
- **THEN** waiter timeout or disconnect SHALL NOT cancel, replay, or duplicate the command

### Requirement: Gameplay commands execute through one strict FIFO
The system SHALL assign monotonically increasing sequence numbers and process world-changing commands through a bounded queue with exactly one consumer and at most one running command.

#### Scenario: Concurrent commands preserve order
- **WHEN** multiple valid execute commands are accepted concurrently
- **THEN** they SHALL receive unique monotonic sequence numbers
- **THEN** the consumer SHALL begin eligible commands in sequence order
- **THEN** at most one command SHALL be running

#### Scenario: Queue deadline races dispatch
- **WHEN** queue expiration and worker dispatch compete for the same command
- **THEN** one atomic compare-and-swap transition SHALL win
- **THEN** an expired command SHALL never execute or emit an action receipt

### Requirement: Status is an immediate read-only projection
`mc_status` SHALL read caller-authorized command/controller projection state without creating a command, entering the gameplay FIFO, calling the runtime, or obtaining a fresh world observation.

#### Scenario: Status during long execution
- **WHEN** status is requested while a command is running
- **THEN** it SHALL return immediately with projection version, update time, active phase, budget usage, queue summary, and recovery state

#### Scenario: Caller requests another scope's command
- **WHEN** a caller queries a command outside its authorized caller scope
- **THEN** status SHALL reject or hide the command without disclosing its payload or receipts

#### Scenario: Caller needs live world state
- **WHEN** a caller needs a fresh runtime observation
- **THEN** it SHALL submit an atomic observe action through `mc_execute`

### Requirement: Stop is a durable global cancellation barrier
`mc_stop` SHALL persist a global stop request, cancellation intent for the active command, and cancellation of all not-yet-started commands before best-effort runtime signaling, while only the single consumer may commit active-command and stop outcomes.

#### Scenario: Stop arrives during active execution
- **WHEN** a stop request is accepted while a command is running
- **THEN** the gateway SHALL immediately persist cancellation intent and signal cooperative cancellation
- **THEN** no queued gameplay command SHALL start before the active command is cleaned up and the stop barrier completes

#### Scenario: Stop clears pending work
- **WHEN** a stop barrier is accepted
- **THEN** every command that has not started SHALL atomically become `cancelled_by_stop`
- **THEN** targeted, partial, and pause semantics SHALL NOT be available

#### Scenario: Stop cannot prove safe cancellation
- **WHEN** receipt, idle, and fresh-observation reconciliation cannot establish the active outcome
- **THEN** stop SHALL return `RECOVERY_INCOMPLETE`
- **THEN** the controller SHALL remain quarantined

### Requirement: Durable caller-scoped idempotency prevents duplicate mutation
Production SHALL enforce uniqueness of `(caller_scope, request_id)` against a canonical normalized request hash across process restarts.

#### Scenario: Identical request is resubmitted
- **WHEN** the same caller scope and request ID are submitted with the same canonical request
- **THEN** the gateway SHALL return the original command and current or terminal projection
- **THEN** no duplicate command or world mutation SHALL be created

#### Scenario: Request ID is reused for different content
- **WHEN** the same caller scope and request ID are submitted with a different canonical request
- **THEN** the gateway SHALL return `IDEMPOTENCY_CONFLICT`

#### Scenario: Terminal payload retention expires
- **WHEN** ordinary command payload or result retention expires
- **THEN** a compact idempotency tombstone SHALL continue to prevent the same caller scope and request ID from creating a new mutation

### Requirement: Command facts and recovery are durable without automatic replay
Production SHALL persist command identity, request hash, queue sequence, lifecycle transitions, cancellation facts, budgets, receipts, results, checkpoints, and recovery attempts in SQLite, and SHALL NOT automatically replay unfinished state-changing commands.

#### Scenario: Process restarts with unfinished work
- **WHEN** startup finds queued and running or reconciling commands from the previous process
- **THEN** queued commands SHALL become `interrupted_before_start`
- **THEN** active commands SHALL become `blocked_unknown`
- **THEN** the controller SHALL start quarantined and neither class SHALL replay

### Requirement: Composite budgets bound all command work
The command executor SHALL enforce time, action-count, attempt, travel, block-change, damage, protected-item, and configured resource budgets across every strategy step, retry, and validation attempt in the parent command.

#### Scenario: Budget is exhausted
- **WHEN** a receipt or pending step reaches an effective budget limit
- **THEN** the executor SHALL request cooperative cancellation and return `BUDGET_EXHAUSTED` after reconciliation
- **THEN** a strategy SHALL NOT obtain a fresh budget by retrying or changing internal phase

#### Scenario: Step is authorized before runtime dispatch
- **WHEN** the executor is ready to dispatch a state-changing step
- **THEN** it SHALL durably reserve a conservative maximum cost and correlation identity before calling the runtime
- **THEN** it SHALL atomically settle actual receipt usage and release unused reservation afterward

#### Scenario: Process exits after reservation
- **WHEN** the process exits after a step reservation but before receipt settlement
- **THEN** recovery SHALL inspect the original correlation and SHALL NOT issue the step again

### Requirement: Public results and errors are structured
Public tools SHALL return typed identity, state, projection, output, receipt summary, evidence eligibility, and structured error fields including phase, outcome knowledge, possible world mutation, resubmission guidance, and operator action.

#### Scenario: Outcome may be unknown
- **WHEN** runtime failure leaves possible unexplained world mutation
- **THEN** the result SHALL set `outcome_known=false` and `world_may_have_changed=true`
- **THEN** it SHALL NOT claim ordinary failure or authorize automatic retry

