## ADDED Requirements

### Requirement: Review plugins declare runtime capabilities
Each review plugin MAY declare required OBS, interactivity, host-service, and lifecycle capabilities, and the CLI SHALL validate them before executing a scene.

#### Scenario: Required capability is unavailable
- **WHEN** a plugin requires OBS, interactive mode, or a host service that is not available
- **THEN** the run SHALL fail with an actionable error before mutating OBS or creating attempt evidence

### Requirement: Review plugins can prepare runtime evidence
The review runner SHALL support plugins that prepare and dispose run-level and attempt-level resources and contribute URL parameters, technical assertions, typed artifacts, and scalar observations to an attempt.

#### Scenario: Prepared attempt completes
- **WHEN** a plugin prepares an attempt and browser capture completes
- **THEN** the runner SHALL merge plugin and browser assertions and persist all declared artifacts and observations atomically

#### Scenario: Prepared attempt fails or is interrupted
- **WHEN** preparation, capture, persistence, or operator interaction raises or is interrupted
- **THEN** attempt and run cleanup SHALL execute once and any safely completed evidence SHALL be retained

### Requirement: Version-two evidence accepts optional audio evidence
Version-two attempt records SHALL remain readable with their original required fields and MAY include audio WAV, backend report, and scalar observation fields.

#### Scenario: Historical evidence is loaded
- **WHEN** a version-one or version-two run without audio extensions is validated
- **THEN** the reader SHALL preserve its existing validity and stable-round behavior

#### Scenario: Audio feature evidence is validated
- **WHEN** a feature declares audio and backend-report artifacts as required
- **THEN** stable-round validation SHALL require valid in-run files and matching artifact digests for both fields

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
