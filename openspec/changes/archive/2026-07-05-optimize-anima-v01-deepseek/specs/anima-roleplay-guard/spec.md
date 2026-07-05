## ADDED Requirements

### Requirement: Assistant-flavor drift detection
The system SHALL detect assistant-flavor drift in recent Anima output using a narrow forbidden phrase list.

#### Scenario: Forbidden helper phrase detected
- **WHEN** recent assistant output contains "作为 AI"
- **THEN** the roleplay guard SHALL mark the next turn as needing correction

#### Scenario: Generic advice phrase detected
- **WHEN** recent assistant output contains "以下是几点建议"
- **THEN** the roleplay guard SHALL mark the next turn as needing correction

#### Scenario: Clean Anima output is not corrected
- **WHEN** recent assistant output contains no configured assistant-flavor phrase
- **THEN** the roleplay guard SHALL NOT inject a correction section

### Requirement: One-turn correction injection
The system SHALL inject a short correction prompt section for exactly one turn after assistant-flavor drift is detected.

#### Scenario: Correction section is injected once
- **WHEN** assistant-flavor drift was detected on the previous assistant turn
- **THEN** the next prompt compilation SHALL include a correction section
- **THEN** the correction section SHALL instruct the model to return directly to Anima voice

#### Scenario: Correction expires after one turn
- **WHEN** a correction section has already been injected for the current drift event
- **THEN** the following prompt compilation SHALL NOT inject the same correction again unless new drift is detected

#### Scenario: Correction is not persisted into persona or memory
- **WHEN** a correction section is injected
- **THEN** it SHALL NOT modify `config/personas/anima.v0.1.yaml`
- **THEN** it SHALL NOT be stored as long-term memory content

### Requirement: Roleplay guard prompt ordering
The correction section SHALL be ordered as runtime guidance that is stronger than memory context but separate from the static persona.

#### Scenario: Correction appears before memory
- **WHEN** correction and memory sections are both present
- **THEN** the correction section SHALL appear before memory in the compiled prompt

#### Scenario: Static persona remains unchanged
- **WHEN** correction is active
- **THEN** the persona section SHALL still be sourced from the configured persona
- **THEN** correction content SHALL remain a separate runtime section
