## ADDED Requirements

### Requirement: Review mode is local-only
The standalone livestream page SHALL provide an explicit review mode that uses an in-memory event source and SHALL NOT create a Socket.IO network connection or invoke Bilibili, AI, or TTS services.

#### Scenario: Review page starts privately
- **WHEN** the page loads with `review=1`
- **THEN** it SHALL render review status and data without creating a backend connection

#### Scenario: Legacy demo entry is used
- **WHEN** the page loads with `demo=1`
- **THEN** it SHALL map to the local baseline review scene without creating a backend connection

### Requirement: Review scenes are deterministic
The review system SHALL select a named scene from URL parameters and emit a fixed ordered timeline of canonical status and danmaku events.

#### Scenario: Known scene is selected
- **WHEN** the page loads with a supported `scene` value
- **THEN** it SHALL emit that scene's fixed events in declared order

#### Scenario: Unknown scene is selected
- **WHEN** the page loads with an unsupported `scene` value
- **THEN** it SHALL warn locally and fall back to the baseline scene

### Requirement: Browser attempts are isolated
The local review runner SHALL create a fresh Playwright browser context for every scene attempt and SHALL use a 1080 × 1920 viewport.

#### Scenario: A scene is retried
- **WHEN** an operator selects `adjust` or `redo`
- **THEN** the previous context SHALL be closed and the same scene SHALL reopen in a fresh context with fresh fixture state

### Requirement: Browser evidence is captured
The local review runner SHALL capture a screenshot, Playwright trace, console errors, page errors, failed requests, and timestamps for every attempt.

#### Scenario: A scene reaches the human gate
- **WHEN** automated readiness assertions complete
- **THEN** all available browser evidence SHALL be written before the attempt is finalized

#### Scenario: A browser assertion fails
- **WHEN** the page does not become ready or a required element is missing
- **THEN** failure evidence SHALL be preserved and the pipeline SHALL stop on the current scene

### Requirement: Human verdict gates progression
The local review runner SHALL accept only `pass`, `adjust`, or `redo` as scene verdicts and SHALL NOT advance to a later scene unless the current scene is passed.

#### Scenario: Operator passes a scene
- **WHEN** the operator records `pass`
- **THEN** the attempt SHALL be finalized and the runner MAY advance to the next approved scene

#### Scenario: Operator requests adjustment or redo
- **WHEN** the operator records `adjust` or `redo`
- **THEN** the verdict and note SHALL be preserved and the runner SHALL remain on the current scene

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
