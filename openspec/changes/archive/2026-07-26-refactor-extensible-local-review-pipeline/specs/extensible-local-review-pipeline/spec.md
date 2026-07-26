## ADDED Requirements

### Requirement: Review features use a shared typed contract
The local review pipeline SHALL select review features from a static registry and SHALL derive scene identity, order, URL selection, readiness metadata, and workflow fingerprint input from each feature's single typed definition.

#### Scenario: A future feature is registered
- **WHEN** a new standalone page supplies a review definition and page adapter
- **THEN** the generic orchestrator SHALL run it without livestream-specific branches

### Requirement: Automatic review is the default
The review CLI SHALL execute automatic technical assertions by default and SHALL reserve human verdicts for an explicit interactive mode.

#### Scenario: Automatic scene assertions pass
- **WHEN** all declared structural assertions and required evidence complete
- **THEN** the scene outcome SHALL be `passed` without a human verdict

#### Scenario: Automatic scene assertions fail
- **WHEN** a structural assertion or evidence requirement fails
- **THEN** the scene outcome SHALL be `failed`, evidence SHALL be retained, and independent later scenes MAY continue without automatic retry

### Requirement: Full review automates OBS
The full review profile SHALL use OBS WebSocket to synchronize a dedicated Browser Source and capture OBS evidence without manual file input.

#### Scenario: OBS is ready
- **WHEN** the full profile starts and OBS is neither streaming nor recording
- **THEN** the runner SHALL update the review source, capture it, verify Chrome/OBS stable-region synchronization, and restore the previous scene

#### Scenario: OBS is unavailable
- **WHEN** the full profile cannot connect or authenticate to OBS
- **THEN** the run SHALL fail preflight with an actionable error and SHALL NOT silently downgrade

### Requirement: Browser-only review is explicit
The CLI SHALL provide `--no-obs` for browser-only diagnostics and SHALL exclude those runs from stable-round counting.

#### Scenario: Browser-only run passes
- **WHEN** every Playwright scene passes with `--no-obs`
- **THEN** the summary SHALL report success but zero stable-round contribution

### Requirement: Review evidence uses version two
New review runs SHALL write append-only version-two run, attempt, artifact, and summary records atomically while retaining read-only compatibility with version-one evidence.

#### Scenario: An attempt is finalized
- **WHEN** its final Chrome and optional OBS capture, trace, errors, and assertions are complete
- **THEN** artifact records SHALL include relative path, hash, byte size, dimensions where applicable, and capture time

#### Scenario: A historical v1 run is discovered
- **WHEN** stable history is loaded
- **THEN** the reader MAY normalize it in memory but SHALL NOT rewrite or manufacture missing artifacts

### Requirement: Stable rounds are validated automatic full runs
Only consecutive automatic version-two runs with complete OBS evidence, identical semantic fingerprints, valid ordered scenes, and valid artifact metadata SHALL contribute to stable rounds.

#### Scenario: Two automatic full runs pass unchanged
- **WHEN** two consecutive validated runs pass every frozen scene
- **THEN** the second summary SHALL report `stable_rounds: 2`
