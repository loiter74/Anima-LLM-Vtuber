## MODIFIED Requirements

### Requirement: Bounded semantic performance marker
The response prompt SHALL request exactly one leading marker in the form `[live2d:<base>|<intensity>|none]`, where the canonical version-one bases are limited to `calm`, `annoyed`, and `surprised`, intensity is limited to `subtle` or `medium`, and the system SHALL NOT make an additional LLM request to create the performance plan.

#### Scenario: Valid canonical semantic marker
- **WHEN** the response begins with a valid canonical version-one marker
- **THEN** the system SHALL create the corresponding semantic plan and strip the marker from visible and synthesized text

#### Scenario: Compatible deprecated semantic marker
- **WHEN** the response begins with a previously supported base or accent
- **THEN** the system SHALL deterministically normalize it to a canonical base and accent before emitting the plan

#### Scenario: Missing or invalid semantic marker
- **WHEN** no valid new or legacy marker can be normalized
- **THEN** the system SHALL use `calm`, `subtle`, `none`, and source `fallback`

### Requirement: Legacy emotion compatibility
The system SHALL normalize the first supported legacy emotion tag into a canonical semantic performance plan and SHALL continue to populate the existing compatible emotion and VAD fields.

#### Scenario: Legacy happy marker
- **WHEN** a response contains `[happy]` and no valid semantic marker
- **THEN** the system SHALL produce a subtle calm plan with source `legacy` and preserve the compatible happy emotion/VAD output

### Requirement: Deterministic model-scoped resolution
The renderer SHALL resolve canonical semantic plans through the active model profile, clamp writes to supported parameter ranges, and fall back to calm when the profile is unavailable.

#### Scenario: Deprecated payload reaches the renderer
- **WHEN** a historical or untyped payload contains a previously supported semantic value
- **THEN** the renderer SHALL normalize it before arming the controller and SHALL NOT expose the deprecated value to the model profile

#### Scenario: Profile is unavailable
- **WHEN** the active model has no performance profile
- **THEN** the renderer SHALL remain in calm idle and SHALL NOT dispatch a raw model action
