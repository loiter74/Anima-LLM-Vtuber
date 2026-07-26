# local-livestream-review Specification
## Purpose
TBD - created by archiving change add-local-livestream-review-pipeline. Update Purpose after archive.
## Requirements
### Requirement: Review mode is local-only
The standalone livestream page SHALL continue to map `review=1` and legacy `demo=1` to its in-memory event source and SHALL NOT create a production Socket.IO connection.

#### Scenario: Legacy demo entry is used
- **WHEN** the page loads with `demo=1`
- **THEN** it SHALL select `baseline` without backend, Bilibili, AI, or TTS access

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

### Requirement: Browser evidence is captured
The local review runner SHALL capture a screenshot, Playwright trace, console errors, page errors, failed requests, and timestamps for every attempt.

#### Scenario: A scene reaches the human gate
- **WHEN** automated readiness assertions complete
- **THEN** all available browser evidence SHALL be written before the attempt is finalized

#### Scenario: A browser assertion fails
- **WHEN** the page does not become ready or a required element is missing
- **THEN** failure evidence SHALL be preserved and the pipeline SHALL stop on the current scene

### Requirement: Human verdict gates progression
The livestream review command SHALL expose `--interactive`; technical failures SHALL NOT be overridable, and `adjust` or `redo` SHALL repeat only the current scene in a fresh context.

#### Scenario: Interactive scene is passed
- **WHEN** automatic gates pass and the operator records `pass`
- **THEN** the human verdict SHALL be stored separately from the automatic outcome and the runner MAY advance

### Requirement: Review evidence is machine-readable
The local review runner SHALL write append-only per-attempt JSON evidence and a run summary under `artifacts/live-review/<run-id>/`.

#### Scenario: Attempt evidence is saved
- **WHEN** an attempt is finalized
- **THEN** its record SHALL include run ID, scene ID, attempt number, verdict, human note, browser and OBS artifact references, collected errors, and start/end timestamps

### Requirement: Stable rounds require unchanged all-pass runs
The local review runner SHALL count a stable round only when every frozen scene passes in order with an unchanged workflow fingerprint.

#### Scenario: Two unchanged rounds pass
- **WHEN** two consecutive complete runs have the same workflow fingerprint and all scenes pass
- **THEN** the run summary SHALL report two stable rounds

#### Scenario: Workflow changes between runs
- **WHEN** scene order, fixtures, viewport, or review behavior changes
- **THEN** the stable round count SHALL reset
