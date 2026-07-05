## Purpose
Defines the accepted behavior and requirements for the memory-panel capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Dual view switching in MemoryPanel
The system SHALL provide a tab bar within MemoryPanel allowing users to switch between list view and graph view.

#### Scenario: Tab bar renders correctly
- **WHEN** MemoryPanel mounts
- **THEN** a tab bar displays with "List" and "Graph" options
- **AND** the active tab is visually distinguished
- **AND** search and filter controls appear below the tab bar (shared across views)

#### Scenario: Default view is list
- **WHEN** MemoryPanel loads for the first time
- **THEN** the list view is active by default
- **AND** the graph view is not rendered until user switches to it (lazy render)

#### Scenario: Graph view lazy initializes
- **WHEN** user switches to graph view for the first time
- **THEN** the graph component initializes, fetches data, and renders nodes/edges
- **AND** subsequent switches to graph view reuse the existing instance (no re-initialization)
