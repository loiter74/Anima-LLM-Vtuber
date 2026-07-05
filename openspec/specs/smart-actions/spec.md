## Purpose
Defines the accepted behavior and requirements for the smart-actions capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Resource-search navigation patterns
系统 SHALL provide smart navigation and mining patterns specifically for resource search.

#### Scenario: Expanding local scan
- **WHEN** a nearby resource is not immediately visible
- **THEN** Bot SHALL use an expanding or spiral search pattern before random movement

#### Scenario: Safe vertical descent
- **WHEN** a resource strategy requires reaching a lower Y-level
- **THEN** Bot SHALL descend using a bounded safe pattern that avoids bedrock, lava, and uncontrolled falls

#### Scenario: Branch mining
- **WHEN** a deep ore strategy requires branch mining
- **THEN** Bot SHALL mine a bounded branch pattern and periodically check safety and search budget

#### Scenario: Abort unsafe navigation
- **WHEN** health, food, hostile pressure, lava, or pathfinding conditions become unsafe
- **THEN** Bot SHALL abort the resource-search navigation and return a structured failure
