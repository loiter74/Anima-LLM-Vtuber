## ADDED Requirements

### Requirement: Anima runtime files reject old-character markers
The system SHALL include regression coverage preventing Anima v0.1 guard and evaluation files from using old-character identity markers.

#### Scenario: Guard text contains no old-character marker
- **WHEN** Anima roleplay guard source is checked
- **THEN** it SHALL NOT contain `久遠寺`
- **THEN** it SHALL NOT contain `有珠`
- **THEN** it SHALL NOT contain `魔女`

#### Scenario: Evaluation fixtures contain no old-character marker
- **WHEN** Anima roleplay evaluation fixtures are checked
- **THEN** they SHALL NOT contain `久遠寺`
- **THEN** they SHALL NOT contain `有珠`
- **THEN** they SHALL NOT contain `魔女`

### Requirement: TDD proof for each runtime correction
Each bug fixed by this change SHALL have a failing test observed before the production fix is applied.

#### Scenario: Correction text is fixed through red-green cycle
- **WHEN** roleplay correction text is wrong
- **THEN** a test SHALL fail because the correction is not Anima-specific
- **THEN** the implementation SHALL be changed only after that failure is observed

#### Scenario: Thinking validation is fixed through red-green cycle
- **WHEN** invalid DeepSeek thinking mode is accepted
- **THEN** a test SHALL fail because config validation does not reject it
- **THEN** the implementation SHALL be changed only after that failure is observed
