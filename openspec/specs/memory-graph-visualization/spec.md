## Purpose
Defines the accepted behavior and requirements for the memory-graph-visualization capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Render knowledge graph from memory data
The system SHALL render an interactive knowledge graph visualization using SVG elements and d3-force layout, displaying Memory V2 atoms as draggable nodes and their relations as labeled edges.

#### Scenario: Graph renders nodes and edges from API data
- **WHEN** MemoryPanel receives memory page data via `memory:list_pages` event
- **THEN** the system parses atoms into graph nodes (id, label, category, importance) and relations into edges (source, target, type, weight)
- **AND** renders nodes as color-coded circles sized by importance (8-32px radius)
- **AND** renders edges as SVG paths colored by relation type

#### Scenario: Force-directed layout positions nodes
- **WHEN** nodes and edges are loaded into the graph
- **THEN** d3-force simulation runs (`forceLink`, `forceCenter`, `forceCollide`, `forceManyBody`)
- **AND** nodes settle into a readable layout with minimal edge overlap

### Requirement: Node drag interaction
The system SHALL allow users to drag individual nodes to reposition them within the graph canvas.

#### Scenario: User drags a node
- **WHEN** user mousedown-drags a node to a new position
- **THEN** the node follows the cursor during drag (d3-drag)
- **AND** connected edges update their paths in real-time
- **AND** on mouseup, the node stays at its new position (force simulation alpha cools)

### Requirement: Node click opens detail panel
The system SHALL open a detail panel when a user clicks a graph node, fetching full page data via `memory:get_page`.

#### Scenario: User clicks a node
- **WHEN** user clicks a node in the graph
- **THEN** a detail panel appears showing: page name, content snippet, category, importance score, related pages list
- **AND** the detail panel includes a "Send to chat" button

### Requirement: Zoom and pan canvas
The system SHALL support zoom (scroll wheel) and pan (drag on empty area) of the graph canvas.

#### Scenario: User zooms with scroll wheel
- **WHEN** user scrolls the mouse wheel over the graph canvas
- **THEN** the entire graph zooms in/out centered on cursor position (d3-zoom)
- **AND** zoom level is clamped between 0.3x and 3x

#### Scenario: User pans on empty canvas
- **WHEN** user drags on an empty area of the graph canvas
- **THEN** the graph viewport pans following the cursor

### Requirement: Search and highlight nodes
The system SHALL filter and highlight nodes matching a search query.

#### Scenario: User types in search bar
- **WHEN** user enters text in the graph search input
- **THEN** nodes whose labels match the query are highlighted (others dimmed)
- **AND** the graph view centers on the first matching node

### Requirement: Filter nodes by category
The system SHALL filter visible nodes by category via a dropdown selector.

#### Scenario: User selects a category filter
- **WHEN** user selects a category from the filter dropdown
- **THEN** only nodes of that category remain fully visible (others fade to 20% opacity)
- **AND** edges connecting to filtered-out nodes are hidden

### Requirement: Edge hover shows relationship label
The system SHALL display a tooltip with relationship type when hovering over an edge.

#### Scenario: User hovers over an edge
- **WHEN** user hovers the cursor over an edge path
- **THEN** a tooltip appears showing the relationship type (e.g., "likes", "uses", "knows")
- **AND** the tooltip disappears on mouseout

### Requirement: View switching in MemoryPanel
The system SHALL provide tab-based switching between list view and graph view within MemoryPanel.

#### Scenario: User switches to graph view
- **WHEN** user clicks the "Graph" tab in MemoryPanel
- **THEN** the list view hides and the graph view renders
- **AND** search/filter controls remain visible and functional in both views

#### Scenario: User switches back to list view
- **WHEN** user clicks the "List" tab in MemoryPanel while in graph view
- **THEN** the graph view hides and the list view renders
- **AND** list view state (scroll position, selection) is preserved
