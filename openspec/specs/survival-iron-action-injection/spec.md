## ADDED Requirements

### Requirement: Survival runner uses injected bot-level action functions
The survival iron runner SHALL execute collect, craft, smelt, and equip actions through functions attached to the bot object by the runtime, rather than through self-implemented helpers.

#### Scenario: Collect action delegates to bot._collect
- **WHEN** the survival runner needs to collect blocks for a phase
- **THEN** the runner SHALL call `bot._collect(block_type, count)`
- **THEN** the runner SHALL NOT implement its own pathfinder or dig logic

#### Scenario: Craft action delegates to bot._craft
- **WHEN** the survival runner needs to craft an item for a phase
- **THEN** the runner SHALL call `bot._craft(recipe, count)`
- **THEN** the runner SHALL NOT implement its own recipe lookup or crafting table detection

#### Scenario: Smelt action delegates to bot._smelt
- **WHEN** the survival runner needs to smelt items for a phase
- **THEN** the runner SHALL call `bot._smelt(item, fuel, count)`
- **THEN** the runner SHALL NOT implement its own furnace opening or output polling

#### Scenario: Equip action delegates to bot._equipTo
- **WHEN** the survival runner needs to equip an item
- **THEN** the runner SHALL call `bot._equipTo(item, destination)`

### Requirement: Action injection happens at bot spawn
The external runtime SHALL attach action functions to the bot object before any command handler can use them.

#### Scenario: Bot object has action functions after spawn
- **WHEN** the bot spawns and the runtime is ready to accept commands
- **THEN** `bot._collect` SHALL be a function
- **THEN** `bot._craft` SHALL be a function
- **THEN** `bot._smelt` SHALL be a function
- **THEN** `bot._equipTo` SHALL be a function

### Requirement: Survival iron timeout is configurable via command params
The `survival_iron` command SHALL accept timeout configuration through its parameters.

#### Scenario: Timeout specified in milliseconds
- **WHEN** Anima sends `survival_iron` with `params.timeout_ms = 120000`
- **THEN** the runner SHALL use 120000ms as its global timeout

#### Scenario: Timeout specified in seconds
- **WHEN** Anima sends `survival_iron` with `params.timeout = 120`
- **THEN** the runner SHALL use 120000ms as its global timeout

#### Scenario: Default timeout
- **WHEN** Anima sends `survival_iron` with no timeout params
- **THEN** the runner SHALL use 25 minutes (1500000ms) as its global timeout
