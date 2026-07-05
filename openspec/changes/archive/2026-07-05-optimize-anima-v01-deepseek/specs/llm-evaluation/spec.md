## ADDED Requirements

### Requirement: Roleplay quality evaluation mode
The LLM evaluation system SHALL support a roleplay quality mode for Anima v0.1 in addition to semantic similarity scoring.

#### Scenario: Roleplay eval uses dialogue cases
- **WHEN** roleplay evaluation mode is selected for Anima v0.1
- **THEN** the evaluator SHALL run the configured Anima dialogue cases
- **THEN** each response SHALL be scored against roleplay criteria rather than factual reference similarity only

#### Scenario: Evaluation output includes roleplay dimensions
- **WHEN** roleplay evaluation completes
- **THEN** output SHALL include forbidden-phrase pass/fail
- **THEN** output SHALL include worldview-marker presence
- **THEN** output SHALL include whether the response stayed in character

### Requirement: Roleplay eval compares runtime policies
The LLM evaluation system SHALL be able to compare DeepSeek runtime policies for Anima v0.1.

#### Scenario: Compare Flash non-thinking and Pro thinking
- **WHEN** roleplay eval is configured with both realtime and complex-reasoning policies
- **THEN** results SHALL record model and thinking mode for each response
- **THEN** results SHALL compare pass rate, latency, and roleplay adherence

#### Scenario: Live eval is optional
- **WHEN** no live provider API key is configured
- **THEN** roleplay evaluation SHALL still support offline deterministic checks
- **THEN** live provider calls SHALL be skipped
