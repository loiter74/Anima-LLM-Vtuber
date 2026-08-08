## Purpose
Define how Anima launches and communicates with an external game-bot runtime after the Minecraft Mineflayer implementation has been extracted from the Anima tree.
## Requirements
### Requirement: Anima can launch an external game bot runtime
The system SHALL allow bot runtime path, entrypoint, package manager, and version to be configured outside the Anima tree.

#### Scenario: External runtime path is configured
- **WHEN** configuration specifies an external runtime path and entrypoint
- **THEN** Anima SHALL launch the runtime from that path
- **THEN** command and event communication SHALL use the stable game-bot contract

#### Scenario: Embedded runtime fallback is disabled after extraction
- **WHEN** the configured runtime has `use_embedded_fallback: false`
- **THEN** Anima SHALL NOT silently launch the removed embedded runtime path
- **THEN** startup SHALL fail visibly if the configured external runtime path or entrypoint is invalid

### Requirement: External runtime lifecycle preserves existing behavior
The system SHALL preserve configured external process start, stop, stderr logging, stdout event reading, and process-exit handling while upgrading command timeout behavior to v2 reconciliation-safe structured outcomes.

#### Scenario: External runtime starts successfully
- **WHEN** the external runtime logs in, emits login, and provides a valid required v2 manifest
- **THEN** Anima SHALL mark it ready and bind its runtime-instance identity

#### Scenario: External runtime command times out
- **WHEN** a state-changing v2 request exceeds its deadline
- **THEN** Anima SHALL begin cooperative cancellation and reconciliation
- **THEN** it SHALL NOT convert transport timeout into a known ordinary failure or automatically retry the mutation

### Requirement: Runtime selection is configurable
The system SHALL allow operators to switch the external runtime path and entrypoint without changing Anima code.

#### Scenario: Operator switches to another external runtime
- **WHEN** the configured external runtime fails parity verification
- **THEN** an operator SHALL be able to point `runtime_path` and `entrypoint` at another compatible runtime
- **THEN** existing Minecraft bridge tests SHALL continue to pass

### Requirement: Capability-only runtime responsibility
The external Node runtime SHALL execute versioned atomic game capabilities and SHALL NOT own structured goals, command queue, curriculum, Skill IR trust, technology unlock, deterministic workflow selection, or Voyager mode state.

#### Scenario: Runtime receives legacy mode command
- **WHEN** a caller sends `set_voyager_mode`, `voyager_live_goal`, or another removed business command
- **THEN** the runtime SHALL return a structured deprecated-command error and SHALL NOT change business state

#### Scenario: Runtime receives a Skill IR program
- **WHEN** a caller attempts to submit an entire Skill IR program directly to Node
- **THEN** the runtime SHALL reject it because Python must interpret and authorize individual steps

### Requirement: Restricted skill execution surface
The production external runtime SHALL NOT execute LLM-generated JavaScript or expose `eval_skill`; it SHALL expose only manifest-declared typed capabilities implemented through wrappers that enforce authorization, correlation, cancellation, budgets, receipts, and single-flight.

#### Scenario: Controller executes learned Skill IR
- **WHEN** the Python command executor reaches an authorized Skill IR ActionStep
- **THEN** it SHALL send only that typed capability and remaining budget to Node
- **THEN** Node SHALL NOT receive arbitrary skill source code

#### Scenario: Arbitrary code command is attempted
- **WHEN** a production caller sends `eval_skill`, raw JavaScript, or an equivalent dynamic-code request
- **THEN** the runtime SHALL return a structured unsupported-command error without evaluating it

### Requirement: External runtime v2 rollout remains rollback-compatible
The v2 runtime SHALL be deployable before the Python cutover while retaining old transport compatibility for one stable application release, and its canonical schema digest SHALL match the Python repository contract.

#### Scenario: Old Python runs against newly deployed Node v2
- **WHEN** operators deploy Node v2 before the Anima cutover
- **THEN** existing supported old protocol operations SHALL continue during the defined compatibility window

#### Scenario: New Python validates schema parity
- **WHEN** the new control plane starts against Node v2
- **THEN** startup SHALL verify supported protocol and required schema/capability guarantees
- **THEN** it SHALL fail visibly rather than downgrade if parity is absent

### Requirement: External runtime retains inspectable correlation evidence
The external runtime SHALL insert a correlation-ledger entry before the first possible world mutation and SHALL retain action status and terminal receipts for at least the configured recovery horizon of the same runtime instance.

#### Scenario: Python reconnects after losing an action response
- **WHEN** Python calls the v2 correlation-inspection operation before the runtime instance or retention horizon changes
- **THEN** Node SHALL return the existing accepted, running, or terminal state without re-executing the action

