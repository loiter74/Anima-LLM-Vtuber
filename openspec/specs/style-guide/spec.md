## Purpose
Defines the accepted behavior and requirements for the style-guide capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: CSS variable to UnoCSS mapping table
The system SHALL provide a complete mapping table from all 21 color CSS variables (`var(--c-*)`) to their UnoCSS class equivalents in STYLE_GUIDE.md.

#### Scenario: Developer looks up a color token
- **WHEN** a developer opens STYLE_GUIDE.md and searches for a color token
- **THEN** they find a row mapping `var(--c-accent)` → `text-c-accent`, `bg-c-accent`, `border-c-accent` etc.
- **AND** each UnoCSS prefix (text/bg/border) is listed for each color token

### Requirement: Component template with UnoCSS classes
The system SHALL provide a Vue SFC template in STYLE_GUIDE.md demonstrating correct UnoCSS class usage for common patterns.

#### Scenario: Developer references the component template
- **WHEN** a developer reads the component template section
- **THEN** they see a complete `<template>` block using UnoCSS classes exclusively
- **AND** the template includes: glass panel, heading, body text, accent button, ghost button

### Requirement: Code review checklist
The system SHALL provide a PR review checklist in STYLE_GUIDE.md covering design system compliance.

#### Scenario: Reviewer checks a PR
- **WHEN** a reviewer runs through the checklist
- **THEN** they verify: new code uses UnoCSS (no raw `var(--c-*)` in style blocks), no hardcoded hex colors, rounded-xl default (no sharp corners), animation durations use `--d-*` tokens, glass panels use `glass`/`glass-strong` shortcuts

### Requirement: Naming convention documentation
The system SHALL document the UnoCSS class naming convention used across the project.

#### Scenario: Developer needs a class name
- **WHEN** a developer needs to style an element
- **THEN** they can reference the naming convention (e.g., `{property}-c-{token}` for colors, `rounded-{size}` for radius, `p-{n}` for spacing)
- **AND** understand that no new hex colors or custom font sizes should be introduced

### Requirement: Migration example
The system SHALL include a before/after example showing migration of a component from CSS variables to UnoCSS.

#### Scenario: Developer migrates an old component
- **WHEN** a developer reads the migration example
- **THEN** they see a side-by-side comparison of the same component written with CSS variables vs UnoCSS classes
- **AND** the example includes common patterns: color tokens, spacing, border-radius, transitions
