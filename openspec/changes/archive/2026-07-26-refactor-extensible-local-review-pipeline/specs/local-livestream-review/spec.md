## MODIFIED Requirements

### Requirement: Review scenes are deterministic
The livestream review system SHALL preserve its eight named scenes and fixed canonical event timelines while deriving all browser and runner metadata from one typed catalog.

#### Scenario: Known scene is selected
- **WHEN** the page loads with a supported `scene` value
- **THEN** it SHALL emit that scene's fixed actions in declared order

#### Scenario: Unknown scene is selected
- **WHEN** the page loads with an unsupported `scene` value
- **THEN** it SHALL warn locally and fall back to `baseline`

### Requirement: Browser attempts are isolated
Every attempt SHALL use a fresh 1080 × 1920 Playwright context and SHALL verify viewport, overflow, expected messages and states, panel placement, hidden collapse/scroll affordances, and Live2D avoidance where applicable.

#### Scenario: A scene completes automatically
- **WHEN** its web-first readiness and structural assertions pass
- **THEN** final browser evidence SHALL be captured before the fresh context is disposed

### Requirement: Human verdict gates progression
The livestream review command SHALL expose `--interactive`; technical failures SHALL NOT be overridable, and `adjust` or `redo` SHALL repeat only the current scene in a fresh context.

#### Scenario: Interactive scene is passed
- **WHEN** automatic gates pass and the operator records `pass`
- **THEN** the human verdict SHALL be stored separately from the automatic outcome and the runner MAY advance

### Requirement: Review mode is local-only
The standalone livestream page SHALL continue to map `review=1` and legacy `demo=1` to its in-memory event source and SHALL NOT create a production Socket.IO connection.

#### Scenario: Legacy demo entry is used
- **WHEN** the page loads with `demo=1`
- **THEN** it SHALL select `baseline` without backend, Bilibili, AI, or TTS access
