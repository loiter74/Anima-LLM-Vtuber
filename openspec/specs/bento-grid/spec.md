## Purpose
Defines the accepted behavior and requirements for the bento-grid capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Dense grid layout
The system SHALL use CSS Grid with `grid-auto-flow: dense` for Bento Grid layout.

#### Scenario: Grid initialization
- **WHEN** BentoGrid component renders
- **THEN** container has `display: grid` and `grid-auto-flow: dense`

#### Scenario: No empty cells
- **WHEN** BentoGrid renders with cards
- **THEN** zero empty cells remain (verified mathematically)

### Requirement: Responsive column count
The system SHALL adjust column count based on viewport width.

#### Scenario: Desktop viewport
- **WHEN** viewport width >= 1280px
- **THEN** grid has 4 columns

#### Scenario: Tablet viewport
- **WHEN** viewport width >= 768px and < 1280px
- **THEN** grid has 2 columns

#### Scenario: Mobile viewport
- **WHEN** viewport width < 768px
- **THEN** grid has 1 column

### Requirement: Card span configuration
The system SHALL support configurable column and row spans per card.

#### Scenario: Wide card
- **WHEN** BentoCard has `span="2x1"` prop
- **THEN** card spans 2 columns and 1 row

#### Scenario: Tall card
- **WHEN** BentoCard has `span="1x2"` prop
- **THEN** card spans 1 column and 2 rows

#### Scenario: Large card
- **WHEN** BentoCard has `span="2x2"` prop
- **THEN** card spans 2 columns and 2 rows

### Requirement: Scroll reveal animation
The system SHALL animate BentoCards as they scroll into viewport.

#### Scenario: Card entrance
- **WHEN** BentoCard scrolls into viewport
- **THEN** card fades in with translateY from 30px to 0

#### Scenario: Staggered entrance
- **WHEN** multiple BentoCards enter viewport
- **THEN** each card animates with 100ms delay

### Requirement: Card content types
The system SHALL support multiple content types within BentoCard.

#### Scenario: Image card
- **WHEN** BentoCard has `type="image"` prop
- **THEN** card displays full-bleed image with hover zoom

#### Scenario: Stat card
- **WHEN** BentoCard has `type="stat"` prop
- **THEN** card displays large number with label

#### Scenario: Chart card
- **WHEN** BentoCard has `type="chart"` prop
- **THEN** card displays chart visualization
