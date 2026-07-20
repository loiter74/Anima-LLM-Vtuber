## MODIFIED Requirements

### Requirement: Live improvisation control layer
The prompt pipeline SHALL include one concise live response-control layer for realtime Anima chat replies without modifying the accepted persona config. Valid active scene guidance SHALL replace the generic improvisation section for that turn; otherwise the generic section SHALL remain the fallback.

#### Scenario: Generic live improvisation section is included
- **WHEN** the prompt pipeline compiles a realtime chat prompt without active scene guidance
- **THEN** the compiled prompt SHALL include the stable generic live improvisation section
- **THEN** the section metadata SHALL expose its stable section name

#### Scenario: Scene guidance replaces generic improvisation
- **WHEN** validated active `SceneGuidance` is present in turn metadata
- **THEN** the compiled prompt SHALL include a bounded scene-guidance section
- **THEN** the compiled prompt SHALL omit the generic live improvisation section

#### Scenario: Persona config remains the source of identity
- **WHEN** either live response-control section is added
- **THEN** the persona section SHALL remain included as the base identity source
- **THEN** the response-control section SHALL NOT require editing persona YAML content or override persona and safety constraints

#### Scenario: Generic improvisation sharpens reply style
- **WHEN** the generic live improvisation section is rendered
- **THEN** it SHALL instruct the model to produce short live-chat replies in Anima voice
- **THEN** it SHALL discourage customer-service phrasing, meta explanations, and rigid advice formatting

#### Scenario: Live response control precedes memory context
- **WHEN** a live response-control section and memory sections are both present
- **THEN** the live response-control section SHALL appear before memory context
- **THEN** memory context SHALL NOT become a conflicting style-setting instruction

### Requirement: Scene guidance prompt validation and containment
The prompt pipeline SHALL consume scene guidance only after contract validation and SHALL contain source failures without blocking the LLM call.

#### Scenario: Malformed scene guidance metadata
- **WHEN** scene guidance metadata is malformed, expired, or schema-incompatible
- **THEN** the prompt pipeline SHALL omit it, include a safe warning, and retain generic improvisation behavior

#### Scenario: Scene guidance is rendered
- **WHEN** active guidance is valid
- **THEN** the rendered section SHALL contain only the current scene summary, response objective, scope, tone, selected technique, meme policy, and explicit avoid/must-address constraints
- **THEN** it SHALL NOT render raw analyzer output or retrieval candidate documents
