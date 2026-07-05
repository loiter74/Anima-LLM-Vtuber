## Purpose
Defines the accepted behavior and requirements for the hover-physics capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Card hover scale effect
The system SHALL apply scale-105 transform on card hover with physics-based easing.

#### Scenario: GlassPanel hover
- **WHEN** user hovers over GlassPanel component
- **THEN** panel scales to 1.05 with 700ms ease-out duration

#### Scenario: Hover containment
- **WHEN** card has hover physics
- **THEN** parent container has `overflow-hidden` to prevent layout shift

### Requirement: Button hover feedback
The system SHALL provide immediate visual feedback on button hover.

#### Scenario: Accent button hover
- **WHEN** user hovers over AnimatedButton with variant="accent"
- **THEN** button background changes to `--c-accent-hover` with glow shadow

#### Scenario: Ghost button hover
- **WHEN** user hovers over AnimatedButton with variant="ghost"
- **THEN** button text changes to `--c-accent` with soft background

### Requirement: Image hover zoom
The system SHALL zoom images on hover within overflow-hidden containers.

#### Scenario: Image card hover
- **WHEN** user hovers over image in BentoCard
- **THEN** image scales to 1.05 with 700ms ease-out

#### Scenario: Image hover containment
- **WHEN** image has hover zoom
- **THEN** parent BentoCard has `overflow-hidden`

### Requirement: Interactive element cursor feedback
The system SHALL change cursor to pointer on interactive elements.

#### Scenario: Clickable element
- **WHEN** user hovers over clickable element
- **THEN** cursor changes to `pointer`

#### Scenario: Disabled element
- **WHEN** user hovers over disabled button
- **THEN** cursor changes to `not-allowed`

### Requirement: Hover state transition smoothness
The system SHALL use cubic-bezier easing for smooth hover transitions.

#### Scenario: Transition timing
- **WHEN** hover effect triggers
- **THEN** transition uses `cubic-bezier(0.16, 1, 0.3, 1)` easing
