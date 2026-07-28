## MODIFIED Requirements

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
