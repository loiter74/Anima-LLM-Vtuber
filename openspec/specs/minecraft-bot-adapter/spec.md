## Purpose
Define the Minecraft compatibility adapter that preserves existing Anima Minecraft behavior while delegating transport and runtime execution through the generic game-bot layer.

## Requirements

### Requirement: Minecraft bridge remains compatible during extraction
The Minecraft compatibility adapter SHALL preserve the existing `send_command(action, params, timeout)` behavior while delegating transport details to the generic game-bot layer.

#### Scenario: Existing caller sends Minecraft command
- **WHEN** an existing Anima module calls `MinecraftBridge.send_command("status", {}, timeout=5.0)`
- **THEN** the call SHALL use the generic game-bot command contract internally
- **THEN** the caller SHALL receive the same response shape as before the migration

#### Scenario: Existing long-running action times out
- **WHEN** an existing caller sends a long-running Minecraft action that times out
- **THEN** the adapter SHALL preserve the existing timeout response and recovery behavior

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
