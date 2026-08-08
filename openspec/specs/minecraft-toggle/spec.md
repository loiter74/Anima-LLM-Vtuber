## Purpose
Defines the accepted behavior and requirements for the minecraft-toggle capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.
## Requirements
### Requirement: Minecraft start/stop via Socket.IO
The system SHALL expose Socket.IO events `minecraft.start` and `minecraft.stop` that allow the frontend to control the Minecraft bot process lifecycle at runtime while gameplay commands remain owned by the Voyager queue.

#### Scenario: Start Minecraft bot
- **WHEN** the frontend emits `minecraft.start` via Socket.IO
- **THEN** the backend SHALL initialize and start the configured external runtime
- **THEN** the backend SHALL validate the required GameBot v2 manifest before accepting execution
- **THEN** the backend SHALL configure the Voyager gateway, repository, queue, controller, and strategies
- **THEN** the backend SHALL emit `minecraft.status` with the connected runtime identity
- **THEN** the LangChain registry SHALL register only `mc_execute`, `mc_status`, and `mc_stop` for Minecraft control

#### Scenario: Stop Minecraft bot
- **WHEN** the frontend emits `minecraft.stop` via Socket.IO
- **THEN** the backend SHALL stop accepting new Voyager commands, persist interruption or blocked-unknown state, stop the worker, stop the bridge, and close persistent resources
- **THEN** shutdown SHALL NOT replay, erase, or silently declare success for unfinished world mutations
- **THEN** the backend SHALL emit `minecraft.status` with `{ connected: false }`

#### Scenario: Connection failure
- **WHEN** the Minecraft server or external runtime is unreachable
- **THEN** the backend SHALL emit `minecraft.status` with a structured connection failure
- **THEN** no gameplay command SHALL be accepted

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

