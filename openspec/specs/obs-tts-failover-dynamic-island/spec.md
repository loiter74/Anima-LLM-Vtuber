# obs-tts-failover-dynamic-island Specification
## Purpose
TBD - created by archiving change refine-obs-tts-failover-dynamic-island. Update Purpose after archive.
## Requirements
### Requirement: Failover transition uses an expanded-to-collapsed island

The OBS TTS failover review SHALL present local takeover as a two-state dynamic island. It SHALL start in an expanded transition state and SHALL collapse once after 1.4 seconds to a quiet persistent local-takeover state.

#### Scenario: Cloud failure first appears

- **WHEN** the `billing-to-local` review notification mounts
- **THEN** it SHALL expose the warning state and the texts “云端语音暂不可用” and “本地语音已接管”
- **AND** its visual state SHALL be `expanded`

#### Scenario: Transition settles

- **WHEN** 1.4 seconds have elapsed after mount
- **THEN** the visual state SHALL change once to `collapsed`
- **AND** the collapsed island SHALL show a success indicator and “本地语音接管”

#### Scenario: Notification is cleaned up early

- **WHEN** the review page is disposed before the collapse deadline
- **THEN** the pending state timer SHALL be cleared
- **AND** no stale callback SHALL mutate detached review content

### Requirement: Island occupies the measured top-bar gap

The island SHALL be centered within the measured horizontal interval between the status rail and the danmaku panel with at least 12 px clearance from each neighbor.

#### Scenario: Standard portrait review layout

- **WHEN** the review viewport is 1080×1920 and both top-bar neighbors are present
- **THEN** the island center SHALL be derived from the status rail right edge and danmaku panel left edge
- **AND** neither expanded nor collapsed bounds SHALL intersect either neighbor

#### Scenario: Neighbor geometry changes

- **WHEN** the viewport or either top-bar neighbor changes size
- **THEN** the island placement and width cap SHALL be recomputed from current bounds

### Requirement: Island uses restrained translucent presentation

The island SHALL reduce substrate prominence while retaining readable foreground status content. It SHALL use existing Animetta design tokens and SHALL NOT apply reduced opacity to the entire element.

#### Scenario: Expanded island is rendered

- **WHEN** the island is expanded
- **THEN** its panel substrate SHALL use approximately 52% tokenized opacity with backdrop blur and a low-alpha tokenized border
- **AND** its foreground text and semantic indicators SHALL retain normal content opacity

#### Scenario: Island collapses

- **WHEN** the island enters the collapsed state
- **THEN** its dimensions, padding, radius, and visible copy SHALL transition within the 200 ms project motion budget
- **AND** it SHALL have no looping or decorative animation

### Requirement: Reduced motion and accessibility remain deterministic

The island SHALL preserve the existing polite status semantics and SHALL provide a non-animated reduced-motion presentation.

#### Scenario: Reduced motion is requested

- **WHEN** `prefers-reduced-motion: reduce` matches at mount
- **THEN** the visual surface SHALL render directly in the collapsed state without an animated transition
- **AND** the live region SHALL still expose the full cloud-to-local transition copy

#### Scenario: Review evidence is collected

- **WHEN** OBS review evidence is captured after audio completion
- **THEN** the final visual state SHALL be `collapsed`
- **AND** existing audio, backend, performance, lip-sync, privacy, and cleanup evidence SHALL remain available
