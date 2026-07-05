## Purpose
Defines the accepted behavior and requirements for the scroll-driven-animations capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Image scale-fade on scroll
The system SHALL animate images from scale 0.8 to 1.0 as they scroll into view, and fade to opacity 0.2 as they scroll out.

#### Scenario: Image entering viewport
- **WHEN** image scrolls into viewport from bottom
- **THEN** image scales from 0.8 to 1.0 and opacity from 0 to 1

#### Scenario: Image leaving viewport
- **WHEN** image scrolls out of viewport from top
- **THEN** image opacity decreases to 0.2

### Requirement: Text reveal on scroll
The system SHALL reveal text words sequentially as user scrolls.

#### Scenario: Paragraph scrub reveal
- **WHEN** user scrolls past a paragraph with `data-scroll-reveal` attribute
- **THEN** each word's opacity scrubs from 0.1 to 1.0 sequentially

#### Scenario: Heading fade-in
- **WHEN** heading scrolls into viewport
- **THEN** heading fades in with translateY from 20px to 0

### Requirement: Pinned sections
The system SHALL support pinned sections where title stays fixed while content scrolls.

#### Scenario: Left-pinned title
- **WHEN** section has `data-pin="left"` attribute
- **THEN** title stays fixed on left while gallery scrolls on right

#### Scenario: Top-pinned header
- **WHEN** section has `data-pin="top"` attribute
- **THEN** header stays at top while content scrolls beneath

### Requirement: Staggered card reveal
The system SHALL reveal cards with staggered timing.

#### Scenario: Grid card stagger
- **WHEN** grid of cards scrolls into viewport
- **THEN** each card fades in with 100ms delay between them

### Requirement: Scroll progress indicator
The system SHALL provide visual feedback for scroll progress.

#### Scenario: Progress bar
- **WHEN** user scrolls down the page
- **THEN** progress bar at top fills proportionally to scroll position
