## Purpose
Defines the accepted behavior and requirements for the gsap-integration capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: GSAP core library integration
The system SHALL include GSAP 3.x as a dependency and register ScrollTrigger plugin globally.

#### Scenario: GSAP installation
- **WHEN** developer runs `pnpm install`
- **THEN** `gsap` package is installed in `node_modules`

#### Scenario: ScrollTrigger registration
- **WHEN** application starts (`main.ts` executes)
- **THEN** `gsap.registerPlugin(ScrollTrigger)` is called once

### Requirement: useGsap composable
The system SHALL provide a `useGsap` composable that manages GSAP context lifecycle automatically.

#### Scenario: Context creation
- **WHEN** component uses `useGsap(callback)` and mounts
- **THEN** `gsap.context(callback)` is created and stored

#### Scenario: Context cleanup
- **WHEN** component unmounts
- **THEN** `ctx.revert()` is called to clean up all GSAP animations

#### Scenario: Multiple animations in one context
- **WHEN** callback creates multiple tweens
- **THEN** all tweens are grouped in the same context for batch cleanup

### Requirement: useScrollTrigger composable
The system SHALL provide a `useScrollTrigger` composable that wraps ScrollTrigger configuration.

#### Scenario: Basic scroll trigger
- **WHEN** component uses `useScrollTrigger(elementRef, { start: 'top 80%' })`
- **THEN** ScrollTrigger is created when element enters viewport at 80% from top

#### Scenario: Scrub animation
- **WHEN** component uses `useScrollTrigger(elementRef, { scrub: true })`
- **THEN** animation progress is tied to scroll position

#### Scenario: Pin section
- **WHEN** component uses `useScrollTrigger(elementRef, { pin: true })`
- **THEN** element stays fixed while scroll continues

### Requirement: useHoverPhysics composable
The system SHALL provide a `useHoverPhysics` composable for physics-based hover effects.

#### Scenario: Scale on hover
- **WHEN** user hovers over element with `useHoverPhysics(el, { scale: 1.05 })`
- **THEN** element scales to 1.05 with 700ms ease-out duration

#### Scenario: Overflow containment
- **WHEN** element has hover physics applied
- **THEN** parent element has `overflow-hidden` to prevent layout shift

#### Scenario: Touch device fallback
- **WHEN** device is touch-based (detected via `useMobile`)
- **THEN** hover physics is disabled, CSS transition used instead

### Requirement: prefers-reduced-motion support
The system SHALL respect `prefers-reduced-motion` media query.

#### Scenario: Reduced motion preference
- **WHEN** user has `prefers-reduced-motion: reduce` set
- **THEN** all GSAP animations are disabled, instant state changes used instead
