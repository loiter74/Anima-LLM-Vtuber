# semantic-live2d-performance Specification

## Purpose
TBD - created by archiving change add-semantic-live2d-performance-control. Update Purpose after archive.
## Requirements
### Requirement: Bounded semantic performance marker
The response prompt SHALL request exactly one leading marker in the form `[live2d:<base>|<intensity>|<accent>]`, where values are limited to the version-one semantic vocabulary. The system SHALL NOT make an additional LLM request to create the performance plan.

#### Scenario: Valid semantic marker
- **WHEN** the response begins with a valid version-one marker
- **THEN** the system SHALL create the corresponding semantic plan and strip the marker from visible and synthesized text

#### Scenario: Missing or invalid semantic marker
- **WHEN** no valid new or legacy marker can be normalized
- **THEN** the system SHALL use `calm`, `subtle`, `none`, and source `fallback`

### Requirement: Legacy emotion compatibility
The system SHALL normalize the first supported legacy emotion tag into a semantic performance plan and SHALL continue to populate the existing emotion and VAD fields.

#### Scenario: Legacy happy marker
- **WHEN** a response contains `[happy]` and no valid semantic marker
- **THEN** the system SHALL produce a subtle cheerful plan with source `legacy` and preserve the compatible happy emotion/VAD output

### Requirement: Semantic-only audio delivery
Audio delivery SHALL carry an optional versioned semantic performance plan and SHALL NOT expose model parameter values or motion group indices from the LLM response path.

#### Scenario: Streaming speech starts
- **WHEN** the first valid PCM chunk starts a streaming response
- **THEN** `audio_stream_start` SHALL include the validated performance plan and existing task identity

#### Scenario: TTS is unavailable
- **WHEN** a turn produces no playable audio
- **THEN** the renderer SHALL remain in calm idle without applying the response plan

### Requirement: Deterministic model-scoped resolution
The renderer SHALL resolve semantic plans through the active model profile, clamp writes to supported parameter ranges, and fall back to calm when the profile or requested semantic capability is unavailable.

#### Scenario: Unsupported semantic capability
- **WHEN** the active model profile does not support the requested base or accent
- **THEN** the renderer SHALL apply calm idle and SHALL NOT dispatch a raw model action

### Requirement: Safe low-cardinality observations
The system SHALL observe normalized source, base, accent, fallback category, stale drops, and audio-to-performance delay without recording response text, raw markers, or local model paths.

#### Scenario: Invalid marker falls back
- **WHEN** marker validation fails
- **THEN** the observation SHALL record only the normalized fallback category and bounded plan labels

