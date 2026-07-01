## ADDED Requirements

### Requirement: Real client capture mode configuration
The system SHALL provide a Minecraft client viewer configuration that can enable or disable real-client capture independently from the Mineflayer action bot and browser debug viewer.

#### Scenario: Client viewer disabled
- **WHEN** real-client capture is disabled
- **THEN** the Mineflayer action bot starts without requiring a viewer account or real Minecraft client

#### Scenario: Client viewer enabled
- **WHEN** real-client capture is enabled with a viewer username and mode
- **THEN** the bridge passes the viewer configuration to the Node bot runtime

### Requirement: Viewer account status reporting
The system SHALL report whether the configured viewer account is online, waiting, bound to the bot, or failed to bind.

#### Scenario: Viewer account not online
- **WHEN** real-client capture is enabled and the viewer account is not present on the server
- **THEN** the bot emits a viewer status indicating it is waiting for the configured viewer account

#### Scenario: Viewer account online
- **WHEN** the configured viewer account is detected on the server
- **THEN** the bot emits a viewer status indicating that the viewer account is online

### Requirement: Spectator follow binding
The system SHALL support a spectator-follow mode that attempts to bind the real Minecraft client viewer account to the Mineflayer bot perspective when server permissions allow it.

#### Scenario: Spectator follow requested
- **WHEN** spectator-follow mode is enabled and the viewer account is online
- **THEN** the bot attempts or reports the command needed to spectate the Mineflayer bot target

#### Scenario: Spectator follow succeeds
- **WHEN** the spectator binding command succeeds
- **THEN** the bot emits a viewer status indicating the viewer account is following the Mineflayer bot

#### Scenario: Spectator follow fails
- **WHEN** the spectator binding command fails or times out
- **THEN** the bot emits a non-fatal viewer status error while keeping the Mineflayer action bot running

### Requirement: Debug viewer fallback
The system MUST keep the existing browser first-person viewer available as a debug-only surface and MUST NOT require it for real-client capture.

#### Scenario: Real client capture active
- **WHEN** real-client capture is enabled
- **THEN** the system identifies the real Minecraft client as the intended capture surface and treats the browser viewer as optional debug output

#### Scenario: Debug viewer unavailable
- **WHEN** the browser debug viewer is disabled or fails to start
- **THEN** real-client capture status reporting and Mineflayer action execution continue independently

### Requirement: Structured AI gameplay state remains authoritative
The system SHALL continue to use Mineflayer structured state as the primary AI gameplay input for the first phase of real-client capture.

#### Scenario: Bot state collected
- **WHEN** the Mineflayer action bot reports position, health, food, inventory, nearby blocks, nearby entities, or current action
- **THEN** Animetta uses that structured state for planning regardless of whether a real client capture window is active

#### Scenario: Visual capture not configured
- **WHEN** no screenshot or OBS capture feed is configured
- **THEN** Minecraft action planning remains available through structured Mineflayer state
