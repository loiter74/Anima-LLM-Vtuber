# extensible-local-review-pipeline Specification
## Purpose
TBD - created by archiving change add-obs-tts-failover-review-scene. Update Purpose after archive.
## Requirements
### Requirement: Review plugins declare runtime capabilities
Each review plugin MAY declare required OBS, interactivity, host-service, and lifecycle capabilities, and the CLI SHALL validate them before executing a scene.

#### Scenario: Required capability is unavailable
- **WHEN** a plugin requires OBS, interactive mode, or a host service that is not available
- **THEN** the run SHALL fail with an actionable error before mutating OBS or creating attempt evidence

### Requirement: Review plugins can prepare runtime evidence
The review runner SHALL support plugins that prepare and dispose run-level and attempt-level resources and contribute URL parameters, technical assertions derived from validated runtime data, typed artifacts, and scalar observations to an attempt.

#### Scenario: Prepared attempt completes
- **WHEN** a plugin prepares an attempt and browser capture completes
- **THEN** the runner SHALL merge plugin and browser assertions and persist all declared artifacts and observations atomically

#### Scenario: Prepared attempt fails or is interrupted
- **WHEN** preparation, capture, persistence, or operator interaction raises or is interrupted
- **THEN** attempt and run cleanup SHALL execute once and any safely completed evidence SHALL be retained

#### Scenario: Performance instrumentation is captured
- **WHEN** the Live2D performance review runs in a production-shaped live surface
- **THEN** the review SHALL retain machine-readable state and audio controls in hidden instrumentation without rendering semantic names or status panels in the captured broadcast

### Requirement: Version-two evidence accepts optional audio evidence
Version-two attempt records SHALL remain readable with their original required fields and MAY include a canonical audio WAV, canonical backend report, a named map of additional audio/report sample pairs, and scalar observation fields.

#### Scenario: Historical evidence is loaded
- **WHEN** a version-one or version-two run without audio extensions or named samples is validated
- **THEN** the reader SHALL preserve its existing validity and stable-round behavior

#### Scenario: Single audio feature evidence is validated
- **WHEN** a feature declares canonical audio and backend-report artifacts as required
- **THEN** stable-round validation SHALL require valid in-run files and matching artifact digests for both fields

#### Scenario: Named audio samples are validated
- **WHEN** a feature contributes named audio samples
- **THEN** each sample SHALL contain an in-run WAV and backend report with matching artifact metadata while the canonical fields remain available

### Requirement: OBS audio changes are reversible
The OBS adapter SHALL snapshot and restore Browser Source settings and audio monitoring state when a plugin requests monitored audio.

#### Scenario: Monitored audio succeeds
- **WHEN** a scene requests monitored Browser Source audio
- **THEN** the adapter SHALL enable rerouted audio and monitor-and-output only for that review lifecycle, the runner SHALL mute its separate Playwright Chromium output, and cleanup SHALL restore the previous OBS values

#### Scenario: Browser-only audio review runs
- **WHEN** monitored OBS audio is not active
- **THEN** the runner SHALL NOT mute Playwright solely because the feature is audio-capable

#### Scenario: Monitored audio setup or capture fails
- **WHEN** any OBS operation fails after the snapshot
- **THEN** restoration SHALL still be attempted and the failure SHALL be included in technical evidence without exposing the OBS password

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
