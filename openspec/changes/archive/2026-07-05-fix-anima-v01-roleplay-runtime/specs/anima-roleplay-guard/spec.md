## ADDED Requirements

### Requirement: Anima-specific correction section
The roleplay guard SHALL use Anima v0.1-specific correction text when assistant-flavor drift is detected.

#### Scenario: Correction references Anima world
- **WHEN** a roleplay correction section is generated
- **THEN** it SHALL reference Anima
- **THEN** it SHALL reference the cyber tavern or travelers
- **THEN** it SHALL avoid old-character identity markers

#### Scenario: Correction rejects assistant flavor
- **WHEN** a roleplay correction section is generated
- **THEN** it SHALL prohibit generic assistant phrases such as `作为AI` and `我理解你的意思`
- **THEN** it SHALL instruct the model to answer directly in Anima voice

### Requirement: Assistant-flavor drift detection
The roleplay guard SHALL detect assistant-flavor drift in recent assistant output using a narrow forbidden phrase list.

#### Scenario: Forbidden helper phrase detected
- **WHEN** recent assistant output contains `作为 AI`
- **THEN** the roleplay guard SHALL mark the next turn as needing correction

#### Scenario: Generic advice phrase detected
- **WHEN** recent assistant output contains `以下是几点建议`
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
