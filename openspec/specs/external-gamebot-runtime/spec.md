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
The system SHALL preserve start, stop, timeout, stderr logging, stdout event reading, and process-exit handling when using an external runtime.

#### Scenario: External runtime starts successfully
- **WHEN** the external runtime process logs in and emits a `login` event
- **THEN** Anima SHALL mark the runtime as ready using the same readiness behavior as before extraction

#### Scenario: External runtime command times out
- **WHEN** a command sent to the external runtime exceeds its timeout
- **THEN** Anima SHALL return a standard error response
- **THEN** timeout recovery behavior SHALL match the existing bridge behavior for long-running actions

### Requirement: Runtime selection is configurable
The system SHALL allow operators to switch the external runtime path and entrypoint without changing Anima code.

#### Scenario: Operator switches to another external runtime
- **WHEN** the configured external runtime fails parity verification
- **THEN** an operator SHALL be able to point `runtime_path` and `entrypoint` at another compatible runtime
- **THEN** existing Minecraft bridge tests SHALL continue to pass
