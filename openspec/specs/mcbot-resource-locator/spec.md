## Purpose
Defines the accepted behavior and requirements for the mcbot-resource-locator capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Resource registry
The system SHALL define a registry of supported resource metadata used by Minecraft resource search.

#### Scenario: Normalize aliases
- **WHEN** the bot receives a resource request for `raw_iron`, `iron`, or `iron_ore`
- **THEN** the registry SHALL normalize the request to the same canonical iron resource definition

#### Scenario: Provide strategy metadata
- **WHEN** the locator resolves a supported resource
- **THEN** the registry SHALL provide target blocks, satisfying drops, resource category, ordered search strategies, and search budget metadata

#### Scenario: Reject unknown resource
- **WHEN** the locator receives an unsupported resource name
- **THEN** it SHALL return or throw a structured `UNKNOWN_RESOURCE` failure

### Requirement: Resource locator API
The system SHALL provide a Resource Locator API that finds resource block candidates before collection or mining.

#### Scenario: Locate supported resource
- **WHEN** `locate_resource` is called for a supported resource
- **THEN** the locator SHALL return a structured result containing resource name, source, block, position, distance, strategy, and attempt count

#### Scenario: Locate times out
- **WHEN** all configured search strategies exceed their time or attempt budgets
- **THEN** the locator SHALL return or throw a structured `SEARCH_TIMEOUT` or `RESOURCE_NOT_FOUND` failure

### Requirement: Strategy-based search
The system SHALL select resource search strategies based on resource metadata instead of relying on random movement as the primary search behavior.

#### Scenario: Surface resource search
- **WHEN** the requested resource is a surface resource such as `oak_log`
- **THEN** the locator SHALL prefer surface scanning and expanding local search before any underground strategy

#### Scenario: Shore resource search
- **WHEN** the requested resource is `sand`
- **THEN** the locator SHALL prefer surface or shore-biased scanning and SHALL NOT use branch mining

#### Scenario: Common underground search
- **WHEN** the requested resource is `coal_ore` or `iron_ore`
- **THEN** the locator SHALL prefer nearby remembered points, cave scanning, safe descent, and then conservative mining fallback

#### Scenario: Deep ore search
- **WHEN** the requested resource is `diamond_ore`
- **THEN** the locator SHALL use preferred Y-level metadata and a branch mining strategy after safety checks pass

### Requirement: Resource memory
The system SHALL keep in-process resource memory for discoveries, depleted points, danger points, and recently successful strategies.

#### Scenario: Reuse known discovery
- **WHEN** a known non-depleted resource point is still present and reachable
- **THEN** the locator SHALL prefer it before starting fresh exploration

#### Scenario: Mark depleted point
- **WHEN** a remembered resource block no longer exists or has been mined
- **THEN** the locator SHALL mark that point as depleted and avoid repeatedly selecting it

#### Scenario: Avoid danger point
- **WHEN** a search attempt records a danger point
- **THEN** future locator attempts SHALL avoid that point while selecting candidates within the same run

### Requirement: Structured search failures
The system SHALL expose actionable failure reasons for resource search and collection failures.

#### Scenario: Tool is insufficient
- **WHEN** the requested resource requires a tool tier the bot does not have
- **THEN** the locator SHALL return or throw `TOOL_REQUIRED` with the required tool information

#### Scenario: Area is unsafe
- **WHEN** search detects low health, hostile pressure, lava risk, or unsafe descent conditions
- **THEN** the locator SHALL return or throw `UNSAFE_AREA` with a reason

#### Scenario: Path is blocked
- **WHEN** pathfinding cannot reach a selected candidate
- **THEN** the locator SHALL record the failed point and continue with another candidate or return `PATH_BLOCKED`

### Requirement: First-version resource coverage
The first Resource Locator implementation SHALL support core surface, common underground, iron, and deep ore resources.

#### Scenario: Supported resources
- **WHEN** requests target `oak_log`, `sand`, `stone`, `cobblestone`, `coal`, `coal_ore`, `iron`, `raw_iron`, `iron_ore`, `diamond`, or `diamond_ore`
- **THEN** the locator SHALL resolve them to supported resource definitions

#### Scenario: Unsupported resource
- **WHEN** requests target a resource outside the first-version registry
- **THEN** the locator SHALL fail with `UNKNOWN_RESOURCE` instead of silently random-walking
