## Purpose
Defines the accepted behavior and requirements for the minecraft-toggle capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Minecraft start/stop via Socket.IO
The system SHALL expose Socket.IO events `minecraft.start` and `minecraft.stop` that allow the frontend to control the Minecraft bot lifecycle at runtime.

#### Scenario: Start Minecraft bot
- **WHEN** the frontend emits `minecraft.start` via Socket.IO
- **THEN** the backend SHALL call `init_bridge()` and `bridge.start()` to spawn the Mineflayer subprocess
- **THEN** the backend SHALL emit `minecraft.status` with `{ connected: true, username: "AnimaBot" }` on successful connection
- **THEN** the Minecraft bot tools SHALL be registered in the LangChain tool registry

#### Scenario: Stop Minecraft bot
- **WHEN** the frontend emits `minecraft.stop` via Socket.IO
- **THEN** the backend SHALL call `bridge.stop()` and `cleanup_bridge()` to terminate the Mineflayer subprocess
- **THEN** the backend SHALL emit `minecraft.status` with `{ connected: false }`

#### Scenario: Connection failure
- **WHEN** the Minecraft server is unreachable and the bot fails to connect
- **THEN** the backend SHALL emit `minecraft.status` with `{ connected: false, error: "Connection refused" }`

### Requirement: Frontend Minecraft toggle in Settings panel
The Vue 3 frontend SHALL display a Minecraft bot toggle in the Settings panel (Controls tab) with real-time connection status.

#### Scenario: Toggle displayed
- **WHEN** the user opens the Settings panel
- **THEN** a Minecraft section SHALL be visible with a connect/disconnect button and connection status indicator
- **THEN** the button SHALL use the same visual pattern as the existing Bilibili connect button

#### Scenario: Connection status feedback
- **WHEN** the backend emits `minecraft.status`
- **THEN** the frontend `minecraftStore` SHALL update its `connected` and `isConnecting` state
- **THEN** the UI SHALL reflect the new status immediately (connecting spinner, connected checkmark, disconnected idle)
