## Purpose
Defines the accepted behavior and requirements for the interactive-panel capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Right panel width matches design system specification
The system SHALL render the InteractivePanel (right panel) at 340px width, matching the `design-system/ui-kit.html` specification.

#### Scenario: Desktop layout renders at correct width
- **WHEN** app renders in desktop mode
- **THEN** InteractivePanel width is exactly 340px
- **AND** the central stage flex-fills remaining space

#### Scenario: Mobile layout unaffected
- **WHEN** app renders in mobile mode (`isMobile = true`)
- **THEN** InteractivePanel uses full-width layout (no fixed width)
- **AND** existing mobile behavior is unchanged
