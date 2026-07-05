## ADDED Requirements

### Requirement: DeepSeek thinking mode is validated
The system SHALL reject unsupported DeepSeek thinking mode values at configuration validation time.

#### Scenario: Thinking disabled is accepted
- **WHEN** DeepSeek config contains `thinking: disabled`
- **THEN** config validation SHALL succeed

#### Scenario: Thinking enabled is accepted
- **WHEN** DeepSeek config contains `thinking: enabled`
- **THEN** config validation SHALL succeed

#### Scenario: Invalid thinking mode is rejected
- **WHEN** DeepSeek config contains `thinking: banana`
- **THEN** config validation SHALL fail before provider calls are made

### Requirement: Runtime policy preserves roleplay and reasoning modes
The system SHALL preserve the intended Anima v0.1 DeepSeek runtime policy.

#### Scenario: Realtime policy uses Flash non-thinking
- **WHEN** the interaction is realtime roleplay or danmaku
- **THEN** the selected model SHALL be `deepseek-v4-flash`
- **THEN** thinking mode SHALL be `disabled`

#### Scenario: Complex policy uses Pro thinking
- **WHEN** complex reasoning is explicitly selected
- **THEN** the selected model SHALL be `deepseek-v4-pro`
- **THEN** thinking mode SHALL be `enabled`

#### Scenario: LLM call boundary uses selected policy
- **WHEN** a policy is selected for an LLM call
- **THEN** the provider call or provider configuration SHALL reflect the selected model and thinking mode
