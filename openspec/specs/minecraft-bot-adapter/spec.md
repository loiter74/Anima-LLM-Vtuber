## Purpose
Define the Minecraft compatibility adapter that preserves existing Anima Minecraft behavior while delegating transport and runtime execution through the generic game-bot layer.
## Requirements
### Requirement: Minecraft Socket.IO handlers remain stable
The Minecraft compatibility adapter SHALL preserve existing Socket.IO start, stop, status, command, and viewer event behavior while the runtime moves behind the generic contract.

#### Scenario: Frontend starts Minecraft bot
- **WHEN** the frontend emits the existing Minecraft start event
- **THEN** the handler SHALL start the configured runtime through the compatibility adapter
- **THEN** existing frontend state updates SHALL continue to receive compatible event payloads

#### Scenario: Viewer status is relayed
- **WHEN** the runtime emits `viewer_joined`, `viewer_left`, or `client_viewer_status`
- **THEN** the adapter SHALL relay the event to existing Socket.IO consumers without changing event names during migration

### Requirement: Minecraft implementation moves out of Anima in stages
The system SHALL support moving Mineflayer, survival, crafting, mining, Voyager learning, skill library, benchmark, and tech-tree implementation code out of Anima after contract parity is proven.

#### Scenario: External runtime owns Minecraft command implementation
- **WHEN** Anima sends a Minecraft command through the adapter to an external runtime
- **THEN** the external runtime SHALL implement Minecraft-specific behavior
- **THEN** Anima SHALL NOT need to import Mineflayer runtime files to execute that command

#### Scenario: Embedded runtime is removed only after parity
- **WHEN** tests and smoke checks prove the external runtime matches required behavior
- **THEN** embedded runtime files MAY be removed in a dedicated cleanup step
- **THEN** Anima SHALL keep only the compatibility adapter and generic game-bot integration code

### Requirement: Minecraft runtime execution is internal to the command executor
The Minecraft adapter SHALL expose the external runtime through the typed `GameBotRuntime` port, and application modules outside the approved adapter/command-executor boundary MUST NOT invoke state-changing runtime capabilities or `MinecraftBridge.send_command` directly.

#### Scenario: Executor executes capability
- **WHEN** a Voyager strategy proposes a typed capability step
- **THEN** the controller-owned command executor SHALL invoke the typed runtime port
- **THEN** the adapter SHALL preserve structured observations, errors, and receipts

#### Scenario: Architecture gate finds bypass
- **WHEN** a Python application module outside the approved boundary directly invokes the bridge or a state-changing runtime method
- **THEN** the repository architecture test SHALL fail

### Requirement: Bridge owns transport lifecycle only
`MinecraftBridge` SHALL own external process startup, readiness, transport, event relay, timeout recovery, and shutdown, but SHALL NOT own gameplay mode, queue, curriculum, skill trust, or deterministic workflow selection.

#### Scenario: Runtime connects
- **WHEN** the configured external runtime emits its login event
- **THEN** the bridge SHALL report readiness and provide the typed adapter to the Voyager control plane

### Requirement: Adapter rejects incompatible runtime instances and contracts
The adapter SHALL validate the GameBot v2 manifest before readiness and SHALL bind every request and receipt to the connected runtime instance.

#### Scenario: Runtime lacks required guarantee
- **WHEN** the manifest lacks single-flight, budget enforcement, cooperative cancellation, or receipt-chain support
- **THEN** the adapter SHALL reject production readiness and no execute command SHALL be admitted

#### Scenario: Runtime instance changes mid-command
- **WHEN** a receipt or observation identifies a different runtime instance from the active command binding
- **THEN** the adapter SHALL return a structured runtime-instance error and the controller SHALL reconcile rather than retry

