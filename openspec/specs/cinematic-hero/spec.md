## Purpose
Defines the accepted behavior and requirements for the cinematic-hero capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Full-screen background with parallax
The system SHALL display a full-screen background image with parallax scroll effect.

#### Scenario: Background rendering
- **WHEN** WelcomeScreen mounts
- **THEN** background image covers full viewport with `background-size: cover`

#### Scenario: Parallax scroll
- **WHEN** user scrolls down
- **THEN** background image scrolls at 50% speed of content

### Requirement: Radial gradient wash
The system SHALL apply a radial gradient overlay to darken background edges.

#### Scenario: Gradient application
- **WHEN** WelcomeScreen renders
- **THEN** radial gradient from transparent to black/60% is applied

### Requirement: GSAP entrance timeline
The system SHALL orchestrate element entrance with GSAP timeline.

#### Scenario: Timeline sequence
- **WHEN** WelcomeScreen mounts
- **THEN** elements animate in sequence: title (0s) → subtitle (0.15s) → CTA (0.3s)

#### Scenario: Title animation
- **WHEN** title enters
- **THEN** title fades in with translateY from 40px to 0 over 0.6s

#### Scenario: Subtitle animation
- **WHEN** subtitle enters
- **THEN** subtitle fades in with translateY from 20px to 0 over 0.4s

### Requirement: Dual CTA buttons
The system SHALL display two high-contrast call-to-action buttons.

#### Scenario: Primary CTA
- **WHEN** WelcomeScreen renders
- **THEN** "开始对话" button with `btn-accent` style is displayed

#### Scenario: Secondary CTA
- **WHEN** WelcomeScreen renders
- **THEN** "了解更多" button with `btn-ghost` style is displayed

#### Scenario: CTA entrance animation
- **WHEN** CTA buttons enter
- **THEN** buttons fade in with staggered timing (100ms between)

### Requirement: Particle effects integration
The system SHALL integrate with SceneEffects for ambient particles.

#### Scenario: Sakura particles
- **WHEN** WelcomeScreen is active
- **THEN** sakura petal particles float across screen

### Requirement: Responsive hero layout
The system SHALL adapt hero layout for different screen sizes.

#### Scenario: Desktop layout
- **WHEN** viewport width >= 1024px
- **THEN** title uses `clamp(3rem, 5vw, 5.5rem)` font size

#### Scenario: Mobile layout
- **WHEN** viewport width < 768px
- **THEN** title uses smaller font size, CTAs stack vertically
